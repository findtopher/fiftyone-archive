/**
 * Copyright 2017-2021, Voxel51, Inc.
 */
import { get32BitColor, getAlphaColor } from "../color";
import {
  BACKGROUND_ALPHA,
  DASH_COLOR,
  DASH_LENGTH,
  MASK_ALPHA,
  SELECTED_MASK_ALPHA,
  TEXT_COLOR,
} from "../constants";

import { deserialize, NumpyResult } from "../numpy";
import { BaseState, BoundingBox, Coordinates, Dimensions } from "../state";
import {
  distanceFromLineSegment,
  ensureCanvasSize,
  getRenderedScale,
} from "../util";
import { CONTAINS, CoordinateOverlay, RegularLabel } from "./base";
import { t } from "./util";

interface DetectionLabel extends RegularLabel {
  mask?: string;
  bounding_box: BoundingBox;
}

export default class DetectionOverlay<
  State extends BaseState
> extends CoordinateOverlay<State, DetectionLabel> {
  private colorMap: (key: string | number) => string;
  private imageColors: Uint32Array;
  private static readonly intermediateCanvas: HTMLCanvasElement = document.createElement(
    "canvas"
  );
  private labelBoundingBox: BoundingBox;
  private readonly mask: NumpyResult;
  private selected: boolean;

  constructor(field, label) {
    super(field, label);
    if (this.label.mask) {
      this.mask = deserialize(this.label.mask);
    }
  }

  containsPoint(state: Readonly<State>) {
    const [w, h] = state.config.dimensions;
    const [_, __, ww, wh] = state.windowBBox;
    const pad = (getRenderedScale([ww, wh], [w, h]) * state.strokeWidth) / 2;
    let [bx, by, bw, bh] = this.label.bounding_box;
    [bx, by, bw, bh] = [bx * w, by * h, bw * w + pad, bh * h + pad];

    const [px, py] = state.pixelCoordinates;

    if (px >= bx && py >= by && px <= bx + bw && py <= by + bh) {
      return CONTAINS.CONTENT;
    }

    if (this.isInHeader(state)) {
      return CONTAINS.BORDER;
    }

    return CONTAINS.NONE;
  }

  draw(ctx: CanvasRenderingContext2D, state: Readonly<State>) {
    this.mask && this.drawMask(ctx, state);

    !state.config.thumbnail && this.drawLabelText(ctx, state);

    const selected = this.isSelected(state);
    if (selected) {
      this.strokeRect(ctx, state, DASH_COLOR);
    }

    this.strokeRect(
      ctx,
      state,
      this.getColor(state),
      selected ? [DASH_LENGTH, DASH_LENGTH] : null
    );
  }

  getMouseDistance(state: Readonly<State>): number {
    let [bx, by, bw, bh] = this.label.bounding_box;
    const [w, h] = state.config.dimensions;
    const [px, py] = state.pixelCoordinates;
    [bx, by, bw, bh] = [bx * w, by * h, bw * w, bh * h];

    if (this.isInHeader(state)) {
      return 0;
    }

    const distances = [
      distanceFromLineSegment([px, py], [bx, by], [bx + bw, by]),
      distanceFromLineSegment([px, py], [bx + bw, by], [bx + bw, by + bh]),
      distanceFromLineSegment([px, py], [bx + bw, by + bh], [bx, by + bh]),
      distanceFromLineSegment([px, py], [bx, by + bh], [bx, by]),
    ];

    return Math.min(...distances);
  }

  getPointInfo(state: Readonly<State>) {
    return {
      color: this.getColor(state),
      field: this.field,
      label: this.label,
      type: "Detection",
    };
  }

  getPoints(): Coordinates[] {
    return getDetectionPoints([this.label]);
  }

  private drawLabelText(ctx: CanvasRenderingContext2D, state: Readonly<State>) {
    const labelText = this.getLabelText(state);

    if (!labelText.length) {
      this.labelBoundingBox = null;
      return;
    }
    const color = this.getColor(state);
    const [tlx, tly, _, __] = this.label.bounding_box;
    ctx.beginPath();
    ctx.fillStyle = getAlphaColor(color, BACKGROUND_ALPHA);
    let [ox, oy] = t(state, tlx, tly);
    [ox, oy] = [ox - state.strokeWidth / 2, oy];
    ctx.moveTo(ox, oy);
    const { width } = ctx.measureText(labelText);
    const height = state.fontSize;
    const bpad = state.textPad * 3 + state.strokeWidth;
    const btrx = ox + width + bpad;
    const btry = oy - height - bpad;
    ctx.lineTo(btrx, oy);
    ctx.lineTo(btrx, btry);
    ctx.lineTo(ox, btry);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = TEXT_COLOR;
    const pad = state.textPad + state.strokeWidth;
    ctx.fillText(labelText, ox + pad, oy - pad);

    const rHeight = (height + bpad) / state.canvasBBox[3];
    this.labelBoundingBox = [
      tlx,
      tly - rHeight,
      (width + bpad) / state.canvasBBox[2],
      rHeight,
    ];
  }

  private drawMask(ctx: CanvasRenderingContext2D, state: Readonly<State>) {
    const [maskHeight, maskWidth] = this.mask.shape;
    const maskContext = DetectionOverlay.intermediateCanvas.getContext("2d");
    ensureCanvasSize(DetectionOverlay.intermediateCanvas, [
      maskWidth,
      maskHeight,
    ]);
    const maskImage = maskContext.createImageData(maskWidth, maskHeight);
    const maskImageRaw = new Uint32Array(maskImage.data.buffer);
    const imageColors = new Uint32Array(maskImage.data.buffer);

    const selected = this.isSelected(state);
    if (
      this.colorMap === state.options.colorMap &&
      this.selected === selected
    ) {
      imageColors.set(this.imageColors);
    } else {
      this.colorMap = state.options.colorMap;
      this.selected = selected;
      const bitColor = get32BitColor(
        this.getColor(state),
        selected ? SELECTED_MASK_ALPHA : MASK_ALPHA
      );
      for (let i = 0; i < this.mask.data.length; i++) {
        if (this.mask.data[i]) {
          maskImageRaw[i] = bitColor;
        }
      }
      this.imageColors = imageColors;
    }

    maskContext.putImageData(maskImage, 0, 0);

    const [tlx, tly, w, h] = this.label.bounding_box;
    const [x, y] = t(state, tlx, tly);

    ctx.drawImage(
      maskContext.canvas,
      x,
      y,
      w * state.canvasBBox[2],
      h * state.canvasBBox[3]
    );
  }

  private getLabelText(state: Readonly<State>): string {
    let text =
      this.label.label && state.options.showLabel ? `${this.label.label}` : "";

    if (state.options.showConfidence && !isNaN(this.label.confidence)) {
      text.length && (text += " ");
      text += `(${Number(this.label.confidence).toFixed(2)})`;
    }
    return text;
  }

  private isInHeader(state: Readonly<State>) {
    if (!this.labelBoundingBox) {
      return false;
    }

    const [w, h] = state.config.dimensions;
    const [px, py] = state.pixelCoordinates;
    let [bx, by, bw, bh] = this.labelBoundingBox;
    [bx, by, bw, bh] = [bx * w, by * h, bw * w, bh * h];

    return px >= bx && py >= by && px <= bx + bw && py <= by + bh;
  }

  private strokeRect(
    ctx: CanvasRenderingContext2D,
    state: Readonly<State>,
    color: string,
    dash?: [number, number]
  ) {
    const [tlx, tly, w, h] = this.label.bounding_box;
    ctx.beginPath();
    ctx.lineWidth = state.strokeWidth;
    ctx.strokeStyle = color;
    ctx.setLineDash(dash ? dash : []);
    ctx.moveTo(...t(state, tlx, tly));
    ctx.lineTo(...t(state, tlx + w, tly));
    ctx.lineTo(...t(state, tlx + w, tly + h));
    ctx.lineTo(...t(state, tlx, tly + h));
    ctx.closePath();
    ctx.stroke();
  }
}

export const getDetectionPoints = (labels: DetectionLabel[]): Coordinates[] => {
  let points: Coordinates[] = [];
  labels.forEach((label) => {
    const [tlx, tly, w, h] = label.bounding_box;
    points = [
      ...points,
      [tlx, tly],
      [tlx + w, tly],
      [tlx + w, tly + h],
      [tlx, tly + h],
    ];
  });
  return points;
};
