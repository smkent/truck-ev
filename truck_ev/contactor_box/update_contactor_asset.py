from __future__ import annotations

from pathlib import Path

from build123d import (
    MM,
    Axis,
    BuildPart,
    BuildSketch,
    Circle,
    Compound,
    Locations,
    Mode,
    Plane,
    Pos,
    add,
    export_step,
    extrude,
    import_step,
)


class Assets:
    DIR = Path(__file__).parent.parent / "assets"

    SOURCE = DIR / (
        "sensata-gigavac-gv200-series-open-contactors-drawing-reexported.step"
    )
    DEST = DIR / (
        "sensata-gigavac-gv200-series-open-contactors-drawing-updated.step"
    )


class UpdatedGigavacGV200Contactor(Compound):
    def __init__(self) -> None:
        imported = self._import()
        super().__init__(children=imported.children, label=imported.label)

    def _import(self) -> Compound:

        def _part(num: int, solid: Compound) -> Compound:
            return self._housing(solid) if num == 0 else solid

        imported_model = import_step(Assets.SOURCE)
        imported_model.children = tuple(
            _part(i, solid.transformed(rotate=(90, 0, 0)))
            for i, solid in enumerate(imported_model.children)
        )
        return imported_model

    def _housing(self, solid: Compound) -> Compound:
        line_thickness = 2.04 * MM
        circle_d = 11.14
        circle_pos = Pos(0, (10.66 + line_thickness), 0)
        with BuildPart() as p:
            add(solid)
            base_pattern_faces = (
                p.faces()
                .filter_by(Plane.XY)
                .filter_by_position(Axis.Z, -3.4, 0.1)
                .sort_by(Axis.Z)
            )
            base_pattern_bottom, *_, _base_pattern_top_sample = (
                base_pattern_faces
            )
            line_depth = base_pattern_bottom.center_location.position.Z
            with BuildSketch(base_pattern_bottom), Locations(circle_pos):
                Circle(radius=(circle_d / 2 + line_thickness))
            extrude(amount=line_depth)
            with BuildSketch(base_pattern_bottom), Locations(circle_pos):
                Circle(radius=circle_d / 2)
            extrude(amount=line_depth, mode=Mode.SUBTRACT)
        if not p.part:
            raise RuntimeError("Empty part")
        p.part.color = solid.color
        return p.part


export_step(UpdatedGigavacGV200Contactor(), str(Assets.DEST))
