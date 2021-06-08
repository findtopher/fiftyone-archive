/**
 * Copyright 2017-2021, Voxel51, Inc.
 */

import { TEXT_COLOR } from "../constants";
import { BaseState, BoundingBox, Coordinates } from "../state";
import { getRenderedScale } from "../util";
import { CONTAINS, isShown, Overlay, PointInfo, RegularLabel } from "./base";

interface ClassificationLabel extends RegularLabel {}

export type ClassificationLabels = [string, ClassificationLabel[]][];

export default class ClassificationsOverlay<State extends BaseState>
  implements Overlay<State> {
  private readonly labels: ClassificationLabels;
  private labelBoundingBoxes: { [key: string]: BoundingBox };

  constructor(labels: ClassificationLabels) {
    this.labels = labels;
    this.labelBoundingBoxes = {};
  }

  getColor(
    state: Readonly<State>,
    field: string,
    label: ClassificationLabel
  ): string {
    const key = state.options.colorByLabel ? label.label : field;
    return state.options.colorMap(key);
  }

  isShown(state: Readonly<State>): boolean {
    return this.getFiltered(state).length > 0;
  }

  getSelectData(state: Readonly<State>) {
    const {
      label: { _id: id },
      field,
    } = this.getPointInfo(state);
    return { id, field };
  }

  getMouseDistance(state: Readonly<State>) {
    if (this.getPointInfo(state)) {
      return 0;
    }
    return Infinity;
  }

  containsPoint(state: Readonly<State>): CONTAINS {
    if (this.getPointInfo(state)) {
      return CONTAINS.CONTENT;
    }
    return Infinity;
  }

  getPointInfo(state: Readonly<State>): PointInfo {
    const filtered = this.getFilteredAndFlat(state);
    const [w, h] = state.config.dimensions;
    const [_, __, ww, wh] = state.windowBBox;
    const pad = (getRenderedScale([ww, wh], [w, h]) * state.strokeWidth) / 2;

    for (const [field, label] of filtered) {
      const box = this.labelBoundingBoxes[label._id];

      if (box) {
        let [bx, by, bw, bh] = box;
        [bx, by, bw, bh] = [bx * w, by * h, bw * w + pad, bh * h + pad];

        const [px, py] = state.pixelCoordinates;

        if (px >= bx && py >= by && px <= bx + bw && py <= by + bh) {
          return {
            field: field,
            label,
            type: "Classification",
            color: this.getColor(state, field, label),
          };
        }
      }
    }
  }

  draw(ctx: CanvasRenderingContext2D, state: Readonly<State>) {
    const labels = this.getFilteredAndFlat(state);
    const width = Math.max(
      ...labels.map(
        ([_, label]) => ctx.measureText(this.getLabelText(state, label)).width
      )
    );
    const newBoxes = {};
    let top = state.textPad;

    labels.forEach(([field, label]) => {
      const result = this.strokeClassification(
        ctx,
        state,
        top,
        width,
        field,
        label
      );
      top = result.top;
      if (result.box) {
        newBoxes[label._id] = result.box;
      }
    });

    this.labelBoundingBoxes = newBoxes;
  }

  getPoints() {
    return getClassificationPoints([]);
  }

  private getFiltered(state: Readonly<State>): ClassificationLabels {
    return this.labels.map(([field, labels]) => [
      field,
      labels.filter((label) => isShown(state, field, label)),
    ]);
  }

  private getFilteredAndFlat(
    state: Readonly<State>,
    sort: boolean = true
  ): [string, ClassificationLabel][] {
    let result: [string, ClassificationLabel][] = [];
    this.getFiltered(state).forEach(([field, labels]) => {
      result = [
        ...result,
        ...labels.map<[string, ClassificationLabel]>((label) => [field, label]),
      ];
    });

    if (sort) {
      const store = Object.fromEntries(
        state.options.activeLabels.map((a) => [a, []])
      );
      result.forEach(([field, label]) => {
        store[field].push(label);
      });
      result = state.options.activeLabels.reduce((acc, field) => {
        return [...acc, ...store[field].map((label) => [field, label])];
      }, []);
      result.sort((a, b) => {
        if (a[0] === b[0]) {
          if (a[1].label < b[1].label) {
            return -1;
          } else if (a[1].label > b[1].label) {
            return 1;
          }
          return 0;
        }
      });
    }
    return result;
  }

  isSelected(state: Readonly<State>, label: ClassificationLabel): boolean {
    return state.options.selectedLabels.includes(label._id);
  }

  private strokeClassification(
    ctx: CanvasRenderingContext2D,
    state: Readonly<State>,
    top: number,
    width: number,
    field: string,
    label: ClassificationLabel
  ): { top: number; box?: BoundingBox } {
    const text = this.getLabelText(state, label);
    if (text.length === 0) {
      return { top };
    }
    const color = this.getColor(state, field, label);
    const selected = this.isSelected(state, label);
    const [cx, cy] = state.canvasBBox;

    let [tlx, tly, w, h] = [
      state.textPad + cx,
      top + cy,
      state.textPad * 3 + width,
      state.fontSize + state.textPad * 3,
    ];
    ctx.beginPath();
    ctx.fillStyle = color;
    ctx.moveTo(tlx, tly);
    ctx.lineTo(tlx + w, tly);
    ctx.lineTo(tlx + w, tly + h);
    ctx.lineTo(tlx, tly + h);
    ctx.closePath();
    ctx.fill();

    ctx.fillStyle = TEXT_COLOR;
    ctx.fillText(text, tlx + state.textPad, tly + h - state.textPad);

    tlx -= cx;
    tly -= cy;

    return {
      top: tly + h + state.textPad,
      box: [
        tlx / state.canvasBBox[2],
        tly / state.canvasBBox[3],
        w / state.canvasBBox[2],
        h / state.canvasBBox[3],
      ],
    };
  }

  private getLabelText(
    state: Readonly<State>,
    label: ClassificationLabel
  ): string {
    let text = label.label && state.options.showLabel ? `${label.label}` : "";

    if (state.options.showConfidence && !isNaN(label.confidence)) {
      text.length && (text += " ");
      text += `(${Number(label.confidence).toFixed(2)})`;
    }

    return text;
  }
}

export const getClassificationPoints = (
  labels: ClassificationLabel[]
): Coordinates[] => {
  return [
    [0, 0],
    [0, 1],
    [1, 0],
    [1, 1],
  ];
};
