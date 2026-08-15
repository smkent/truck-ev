from __future__ import annotations

from copy import copy
from enum import IntEnum
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from bdbox import Model, show
from build123d import (
    MM,
    Align,
    Axis,
    BasePartObject,
    BuildPart,
    BuildSketch,
    Circle,
    Color,
    Compound,
    Cylinder,
    Face,
    GeomType,
    GridLocations,
    Joint,
    Kind,
    Location,
    LocationList,
    Locations,
    Mode,
    Part,
    Plane,
    Pos,
    Rectangle,
    RigidJoint,
    Rot,
    RotationLike,
    ShapeList,
    SortBy,
    Vector,
    add,
    chamfer,
    extrude,
    fillet,
    import_step,
    offset,
    scale,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def show_loc(
    loc: Location | Plane | Joint | LocationList, label: str | None = None
) -> None:
    def _show(loc: Location, label: str | None = None) -> None:
        symbol = Compound.make_triad(axes_scale=10).move(loc)
        symbol.label = label or ""
        show(symbol)

    label = label or f"{type(loc).__name__}: {loc}"
    if isinstance(loc, LocationList):
        for single_loc in loc:
            _show(single_loc, label)
    elif isinstance(loc, Joint | Plane):
        _show(loc.location, label)
    else:
        _show(loc, label)


class Assets:
    DIR = Path(__file__).parent.parent / "assets"

    BOX = DIR / "PN-1335.STEP"
    CONTACTOR = DIR / (
        "sensata-gigavac-gv200-series-open-contactors-drawing-updated.step"
    )
    FUSE_BLOCK = DIR / "ETI_D02.step"
    FUSE_HOLDER = DIR / "fuse-holder.step"
    DIN_RAIL = DIR / "dinr135-010.step"


class ManufacturerBox(Compound):
    base_thickness = 3 * MM
    wall_thickness = 5 * MM
    standoff_z = 8 * MM
    standoff_screw_diameter = 3 * MM

    def __init__(self) -> None:
        imported = self._import()
        self.lid, self.body = imported.children
        self.lid.label += " Lid"
        self.body.label += " Body"
        super().__init__(children=imported.children, label=imported.label)

    def _import(self) -> Compound:
        imported_model = import_step(Assets.BOX)
        imported_model.children = (
            solid.transformed(rotate=(90, 90, 0))
            for solid in imported_model.children
        )
        return imported_model

    @cached_property
    def interior_bottom_face(self) -> Face:
        return (
            self.body.faces()
            .filter_by(Plane.XY)
            .filter_by(GeomType.PLANE)
            .filter_by_position(
                Axis.Z, self.base_thickness - 1, self.base_thickness + 1
            )
            .sort_by(SortBy.AREA, reverse=True)[0]
        )

    @cached_property
    def standoff_faces(self) -> ShapeList[Face]:
        return (
            self.body.faces()
            .filter_by(Plane.XY)
            .filter_by(GeomType.PLANE)
            .filter_by_position(Axis.Z, self.standoff_z - 1, self.standoff_z)
        )

    @cached_property
    def standoff_locations(self) -> Sequence[Location]:
        return [f.center_location for f in self.standoff_faces]

    @cached_property
    def standoffs(self) -> Part:
        blank_face = self.interior_bottom_face.without_holes()
        with BuildPart() as p:
            for f in self.standoff_faces:
                extrude(f.without_holes(), amount=-(self.standoff_z + 1))
            add(self.body)
            extrude(
                blank_face,
                amount=(self.standoff_z - self.base_thickness),
                mode=Mode.INTERSECT,
            )
        if not p.part:
            raise RuntimeError("Empty part")
        return p.part


class ContactorBox(Compound):
    class HighVoltageWireSpecs:
        large_wire_radius = (17 * MM) / 2
        connector_radius = (35 * MM) / 2

    def __init__(self, plate_edge_fit: float) -> None:
        self.mbox = ManufacturerBox()
        self.plate_edge_fit = plate_edge_fit
        super().__init__(
            children=[self.mbox.lid, self.body, self.high_voltage_wires],
            label=self.mbox.label,
        )

    @cached_property
    def body_size(self) -> Vector:
        return self.mbox.body.bounding_box().size

    @cached_property
    def body(self) -> Part:
        mbox_body = self.mbox.body
        with BuildPart() as p_box_body:
            add(mbox_body)

            # Cutouts for large wire connectors
            with (
                Locations((0, 0, self.body_size.Z / 2)),
                GridLocations(self.body_size.X, self.body_size.Y / 2, 2, 2),
            ):
                Cylinder(
                    self.HighVoltageWireSpecs.connector_radius,
                    height=self.mbox.wall_thickness * 2,
                    rotation=(0, 90, 0),
                    mode=Mode.SUBTRACT,
                )

            RigidJoint(
                "interior_base",
                joint_location=Plane(
                    self.mbox.interior_bottom_face.location_at(0.5, 0.5)
                ).location,
            )
            standoff_z = (
                self.mbox.standoff_faces.sort_by(SortBy.DISTANCE)[0]
                .position_at(0.5, 0.5)
                .Z
            )
            RigidJoint("center_standoff", joint_location=Pos(0, 0, standoff_z))

        if not p_box_body.part:
            raise RuntimeError("Empty part")
        p_box_body.part.label = f"{mbox_body.label} (modified)"
        p_box_body.part.color = mbox_body.color
        return p_box_body.part

    @cached_property
    def high_voltage_wires(self) -> Part:
        with (
            BuildPart() as p_high_voltage_wires,
            Locations((0, 0, self.body_size.Z / 2)),
            GridLocations(0, self.body_size.Y / 2, 1, 2),
        ):
            Cylinder(
                self.HighVoltageWireSpecs.large_wire_radius,
                height=self.body_size.X * 1.5,
                rotation=(0, 90, 0),
            )
        if not p_high_voltage_wires.part:
            raise RuntimeError("Empty part")
        p_high_voltage_wires.part.label = "High voltage wires"
        p_high_voltage_wires.part.color = Color(0xFF5511, 0xAA)
        return p_high_voltage_wires.part

    @cached_property
    def standoff_cutout_faces(self) -> Compound:
        return offset(
            ShapeList(f.without_holes() for f in self.mbox.standoff_faces),
            mode=Mode.PRIVATE,
        )

    @cached_property
    def standoff_cutouts(self) -> Part:
        with BuildPart() as p:
            for solid in self.mbox.standoffs.solids():
                bbox = solid.bounding_box()
                scale(
                    solid,
                    by=(
                        (bbox.size.X + self.plate_edge_fit) / bbox.size.X,
                        (bbox.size.Y + self.plate_edge_fit) / bbox.size.Y,
                        1,
                    ),
                    about=solid.bounding_box().center(),
                    mode=Mode.ADD,
                )
        if not p.part:
            raise RuntimeError("Empty part")
        return p.part


class MountingPlate(BasePartObject):
    def __init__(
        self,
        contactor_box: ContactorBox,
        plate_thickness: float,
        plate_edge_fit: float,
        plate_sunk_depth: float,
        screw_fit: float,
        rotation: RotationLike = (0, 0, 0.0),
        align: tuple[Align, Align, Align] | None = None,
        mode: Mode = Mode.ADD,
        *,
        print_test: bool = False,
    ) -> None:
        mbox = contactor_box.mbox
        blank_face = mbox.interior_bottom_face.without_holes()
        base_z = mbox.standoff_faces[0].center_location.position.Z
        with BuildPart() as p:
            with BuildSketch(Plane.XY.offset(base_z)):
                offset(
                    copy(blank_face),
                    amount=-plate_edge_fit,
                    mode=Mode.ADD,
                )
                if print_test:
                    with BuildSketch(mode=Mode.SUBTRACT) as sk_cutouts:
                        amount = 10
                        add(copy(blank_face))
                        bbox = mbox.bounding_box()
                        Rectangle(1, bbox.size.Y, mode=Mode.SUBTRACT)
                        add(
                            contactor_box.standoff_cutout_faces,
                            mode=Mode.SUBTRACT,
                        )
                        offset(kind=Kind.INTERSECTION, amount=-amount)
                        fillet(
                            sk_cutouts.vertices(),
                            mbox.standoff_screw_diameter * 2,
                        )
            extrude(amount=plate_thickness)
            chamfer(p.edges().filter_by(Plane.XY), plate_thickness / 8)
            with (
                BuildSketch(Plane.XY.offset(base_z)),
                Locations(mbox.standoff_locations),
            ):
                Circle(radius=(mbox.standoff_screw_diameter + screw_fit) / 2)
            extrude(amount=plate_thickness, mode=Mode.SUBTRACT)
            if plate_sunk_depth > 0:
                with BuildSketch(Plane.XY.offset(base_z)):
                    offset(
                        contactor_box.standoff_cutout_faces,
                        amount=plate_edge_fit / 2,
                        mode=Mode.ADD,
                    )
                extrude(amount=plate_sunk_depth, mode=Mode.SUBTRACT)

            face = p.faces().filter_by(Plane.XY).sort_by(Axis.Z)[-1]
            RigidJoint(
                "box_mount",
                joint_location=Plane(face.location_at(0.5, 0.5))
                .offset(-plate_sunk_depth)
                .location,
            )
            RigidJoint(
                "contactor_attach", joint_location=face.location_at(0.25, 0.25)
            )
            RigidJoint(
                "fuse_block_attach",
                joint_location=face.location_at(0.75, 0.75),
            )
        if not p.part:
            raise RuntimeError("Empty part")
        p.part.label = type(self).__name__
        dest = Rot(rotation)  # ty: ignore[invalid-argument-type]
        super().__init__(part=p.part.moved(dest), align=align, mode=mode)


class GigavacGV200Contactor(Compound):
    mounting_hole_separation = 68.2752 * MM

    class NamedPart(IntEnum):
        HOUSING = 0
        MOUNTING_HOLE_A1 = 1
        MOUNTING_HOLE_A2 = 2
        POST_BASE_A1 = 3
        POST_BASE_A2 = 4
        TOP = 5
        POST_BOLT_A1 = 6
        POST_BOLT_A2 = 7
        WIRE_BLACK = 8
        WIRE_RED = 9
        POST_NUT_A1 = 10
        POST_NUT_A2 = 11

    def __init__(self) -> None:
        imported = self._import()
        super().__init__(children=imported.children, label=imported.label)
        for part in [
            self.NamedPart.HOUSING,
            self.NamedPart.MOUNTING_HOLE_A1,
            self.NamedPart.MOUNTING_HOLE_A2,
        ]:
            solid = self.children[part]
            bbox = solid.bounding_box()
            center = bbox.center()
            RigidJoint(
                part.name.lower(),
                self,
                joint_location=Pos(center.X, center.Y, bbox.min.Z),
            )

    def _import(self) -> Compound:
        def _part(part: self.NamedPart, solid: Compound) -> Compound:
            solid.label = part.name.title()
            return solid

        imported_model = import_step(Assets.CONTACTOR)
        imported_model.children = tuple(
            _part(part, imported_model.children[part])
            for part in self.NamedPart
        )
        return imported_model

    @cached_property
    def simple(self) -> GigavacGV200Contactor:
        exclude_parts = [
            self.NamedPart.POST_BOLT_A1,
            self.NamedPart.POST_BOLT_A2,
        ]
        assembly = copy(self)
        assembly.children = tuple(
            self.children[part]
            for part in self.NamedPart
            if part not in exclude_parts
        )
        return assembly


class FuseBlock(Compound):
    def __init__(self) -> None:
        imported = self._import()
        super().__init__(children=imported.children, label=imported.label)
        RigidJoint(
            "din_rail_center",
            self,
            joint_location=self.children[0].joints["center"].location,
        )

    def _import(self) -> Compound:
        din_rail = self._din_rail().move(Pos(0, 0, -7.5))
        fuse_holders = self._fuse_holders()
        return Compound(
            children=[din_rail, fuse_holders],
            label="Fuse block",
        )

    def _fuse_holders(self) -> Compound:
        imported_model = (
            import_step(Assets.FUSE_HOLDER)
            .transformed(rotate=(0, 90, 0))
            .transformed(offset=(0, -36.5 - 4.35, 36.5))
        )
        imported_model.label = "Fuse holder"
        size = imported_model.bounding_box().size
        return Compound(
            label="fuses",
            children=[
                copy(imported_model).moved(Pos(-size.X, 0, 0)),
                imported_model,
                copy(imported_model).moved(Pos(size.X, 0, 0)),
            ],
        )

    def _din_rail(self) -> Compound:
        imported_model = import_step(Assets.DIN_RAIL).transformed(
            offset=(-50, 0, 0), rotate=(90, 0, 0)
        )
        RigidJoint("center", imported_model, joint_location=Location())
        imported_model.label = "DIN rail 100mm"
        return imported_model


class ContactorBoxAssembly(Model):
    print_test: bool = False
    simple: bool = False

    plate_thickness: float = 5 * MM
    plate_edge_fit: float = 1 * MM
    plate_standoff_fit: float = 1 * MM
    plate_sunk_depth: float = 3 * MM
    screw_fit: float = 0.4 * MM

    def build(self) -> Model.Geometry:
        self.contactor_box.body.joints["center_standoff"].connect_to(
            self.mounting_plate.joints["box_mount"]
        )
        self.mounting_plate.joints["contactor_attach"].connect_to(
            self.contactor.joints["housing"]
        )
        self.mounting_plate.joints["fuse_block_attach"].connect_to(
            self.fuse_block.joints["din_rail_center"]
        )
        return [self.contactor_box, self.mounting_plate, self.components]

    @cached_property
    def contactor(self) -> GigavacGV200Contactor:
        part = GigavacGV200Contactor()
        return part.simple if self.simple else part

    @cached_property
    def fuse_block(self) -> Compound:
        return FuseBlock()

    @cached_property
    def components(self) -> Compound:
        return Compound(
            children=[self.contactor, self.fuse_block], label="Components"
        )

    @cached_property
    def contactor_box(self) -> ContactorBox:
        return ContactorBox(self.plate_edge_fit)

    @cached_property
    def mounting_plate(self) -> Part:
        with BuildPart() as p:
            mp = MountingPlate(
                self.contactor_box,
                self.plate_thickness,
                self.plate_edge_fit,
                self.plate_sunk_depth,
                self.screw_fit,
            )
            for joint in mp.joints.values():
                RigidJoint(joint.label, joint_location=joint.location)
            with (
                Locations(mp.joints["contactor_attach"].location),
                GridLocations(
                    self.contactor.mounting_hole_separation, 0, 2, 1
                ),
            ):
                Cylinder(
                    radius=3,
                    height=self.plate_thickness,
                    align=(Align.CENTER, Align.CENTER, Align.MAX),
                    mode=Mode.SUBTRACT,
                )

        if not p.part:
            raise RuntimeError("empty part")
        p.part.label = mp.label
        return p.part
