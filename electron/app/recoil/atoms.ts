import randomColor from "randomcolor";
import { atom, atomFamily } from "recoil";

export const port = atom({
  key: "port",
  default: parseInt(process.env.FIFTYONE_SERVER_PORT) || 5151,
});

export const stateDescription = atom({
  key: "stateDescription",
  default: {},
});

export const stageInfo = atom({
  key: "stageInfo",
  default: undefined,
});

export const colors = atom({
  key: "colors",
  default: randomColor({ count: 100, luminosity: "dark" }),
});

export const sidebarVisible = atom({
  key: "sidebarVisible",
  default: true,
});

export const currentSamples = atom({
  key: "currentSamples",
  default: [],
});

export const filterInvertIncludeLabels = atomFamily({
  key: "filterInvertIncludeLabels",
  default: false,
});

export const modalFilterInvertIncludeLabels = atomFamily({
  key: "modalFilterInvertIncludeLabels",
  default: false,
});

export const filterIncludeLabels = atomFamily({
  key: "filterIncludeLabels",
  default: [],
});

export const filterLabelConfidenceRange = atomFamily({
  key: "filterLabelConfidenceRange",
  default: [0, 1],
});

export const filterLabelIncludeNoConfidence = atomFamily({
  key: "filterLabelIncludeNoConfidence",
  default: true,
});

export const modalFilterIncludeLabels = atomFamily({
  key: "modalFilterIncludeLabels",
  default: [],
});

export const modalFilterLabelConfidenceRange = atomFamily({
  key: "modalFilterLabelConfidenceRange",
  default: [0, 1],
});

export const modalFilterLabelIncludeNoConfidence = atomFamily({
  key: "modalFilterLabelIncludeNoConfidence",
  default: true,
});

export const activeLabels = atom({
  key: "activeLabels",
  default: {},
});

export const modalActiveLabels = atom({
  key: "modalActiveLabels",
  default: {},
});

export const activeOther = atom({
  key: "activeOther",
  default: {},
});

export const activeTags = atom({
  key: "activeTags",
  default: {},
});
