import {
  mainSample,
  mainSampleQuery as mainSampleQueryGraphQL,
  paginateGroup,
  paginateGroupQuery,
  paginateGroup_query$key,
  pcdSample,
  pcdSampleQuery,
} from "@fiftyone/relay";

import { VariablesOf } from "react-relay";
import { atom, atomFamily, selector, selectorFamily } from "recoil";

import { graphQLSelector, graphQLSelectorFamily } from "recoil-relay";
import type { ResponseFrom } from "../utils";
import {
  AppSample,
  SampleData,
  dataset,
  getBrowserStorageEffectForKey,
  modal,
  modal as modalAtom,
  pinned3DSample,
} from "./atoms";
import { RelayEnvironmentKey } from "./relay";
import { datasetName } from "./selectors";
import { view } from "./view";

type SliceName = string | undefined | null;

export const isGroup = selector<boolean>({
  key: "isGroup",
  get: ({ get }) => {
    return get(dataset)?.mediaType === "group";
  },
});

export const defaultGroupSlice = selector<string>({
  key: "defaultGroupSlice",
  get: ({ get }) => {
    return get(dataset).defaultGroupSlice;
  },
});

export const groupSlice = atomFamily<string, boolean>({
  key: "groupSlice",
  default: null,
});

export const resolvedGroupSlice = selectorFamily<string, boolean>({
  key: "resolvedGroupSlice",
  get:
    (modal) =>
    ({ get }) => {
      return get(groupSlice(modal)) || get(defaultGroupSlice);
    },
});

export const groupMediaTypes = selector<{ name: string; mediaType: string }[]>({
  key: "groupMediaTypes",
  get: ({ get }) => get(dataset).groupMediaTypes,
});

export const groupSlices = selector<string[]>({
  key: "groupSlices",
  get: ({ get }) => {
    return get(groupMediaTypes)
      .map(({ name }) => name)
      .sort();
  },
});

export const defaultPcdSlice = selector<string | null>({
  key: "defaultPcdSlice",
  get: ({ get }) => {
    const { groupMediaTypes } = get(dataset);

    for (const { name, mediaType } of groupMediaTypes) {
      // return the first point cloud slice
      if (["point_cloud", "point-cloud"].includes(mediaType)) {
        return name;
      }
    }

    return null;
  },
});

// export const pinnedSlice = atom<string | null>({
//   key: "pinnedSlice",
//   default: defaultPinnedSlice,
//   effects: [getBrowserStorageEffectForKey("pinnedSlice")],
// });

export const pointCloudSliceExists = selector<boolean>({
  key: "sliceMediaTypeMap",
  get: ({ get }) =>
    get(dataset).groupMediaTypes.some((g) => g.mediaType === "point_cloud"),
});

export const allPcdSlices = selector<string[]>({
  key: "allPcdSlices",
  get: ({ get }) =>
    get(dataset)
      .groupMediaTypes.filter((g) => g.mediaType === "point_cloud")
      .map((g) => g.name),
});

export const activePcdSlices = atom<string[] | null>({
  key: "activePcdSlices",
  default: selector({
    key: "activePcdSlicesDefault",
    get: ({ get }) => {
      const defaultPcdSliceValue = get(defaultPcdSlice);
      return defaultPcdSliceValue ? [defaultPcdSliceValue] : null;
    },
  }),
  effects: [
    // todo: key by dataset name
    getBrowserStorageEffectForKey(`activePcdSlices`, {
      valueClass: "stringArray",
    }),
  ],
});

export const activePcdSliceToSampleMap = atom<{
  [sliceName: string]: SampleData;
}>({
  key: "activePcdSamples",
  default: {},
});

export const currentSlice = selectorFamily<string | null, boolean>({
  key: "currentSlice",
  get:
    (modal) =>
    ({ get }) => {
      if (!get(isGroup)) return null;

      if (modal && get(pinned3DSample)) {
        return get(activePcdSlices)?.at(0);
      }

      return get(groupSlice(modal)) || get(defaultGroupSlice);
    },
});

export const hasPcdSlice = selector<boolean>({
  key: "hasPcdSlice",
  get: ({ get }) => Boolean(get(activePcdSlices)?.length > 0),
});

export const groupField = selector<string>({
  key: "groupField",
  get: ({ get }) => get(dataset).groupField,
});

export const groupId = selector<string>({
  key: "groupId",
  get: ({ get }) => {
    return get(modalAtom)?.sample[get(groupField)]?._id;
  },
});

export const refreshGroupQuery = atom<number>({
  key: "refreshGroupQuery",
  default: 0,
});

export const groupQuery = graphQLSelector<
  VariablesOf<paginateGroupQuery>,
  ResponseFrom<paginateGroupQuery>
>({
  key: "groupQuery",
  environment: RelayEnvironmentKey,
  mapResponse: (response) => response,
  query: paginateGroup,
  variables: ({ get }) => {
    const sample = get(modalAtom).sample;

    const group = get(groupField);

    return {
      dataset: get(datasetName),
      view: get(view),
      filter: {
        group: {
          id: sample[group]._id,
        },
      },
    };
  },
});

const mapSampleResponse = (response) => {
  const actualRawSample = response?.sample?.sample;

  // This value may be a string that needs to be deserialized
  // Only occurs after calling useUpdateSample for pcd sample
  // - https://github.com/voxel51/fiftyone/pull/2622
  // - https://github.com/facebook/relay/issues/91
  if (actualRawSample && typeof actualRawSample === "string") {
    return {
      ...response.sample,
      sample: JSON.parse(actualRawSample),
    };
  }

  return response.sample;
};

export const pcdSampleQueryFamily = graphQLSelectorFamily<
  VariablesOf<pcdSampleQuery>,
  string,
  ResponseFrom<pcdSampleQuery>["sample"]
>({
  key: "pcdSampleQuery",
  environment: RelayEnvironmentKey,
  query: pcdSample,
  variables:
    (pcdSlice) =>
    ({ get }) => {
      const groupIdValue = get(groupId);

      return {
        dataset: get(datasetName),
        view: get(view),
        filter: {
          group: {
            id: groupIdValue,
            slice: pcdSlice,
          },
        },
      };
    },
  mapResponse: mapSampleResponse,
});

export const pcdSamples = atom<string[] | null>({
  key: "pcdSamples",
  default: selector({
    key: "pcdSamplesDefault",
    get: ({ get }) => {
      const defaultPcdSliceValue = get(defaultPcdSlice);
    },
  }),
});

export const groupPaginationFragment = selector<paginateGroup_query$key>({
  key: "groupPaginationFragment",
  get: ({ get }) => get(groupQuery),
});

export const activeModalSample = selectorFamily<
  AppSample | ResponseFrom<pcdSampleQuery>["sample"],
  SliceName
>({
  key: "activeModalSample",
  get:
    (sliceName) =>
    ({ get }) => {
      if (!sliceName || !get(isGroup)) {
        return get(modalAtom).sample;
      }

      if (get(pinned3DSample) || get(activePcdSlices)?.includes(sliceName)) {
        return get(pcdSampleQueryFamily(sliceName)).sample;
      }

      return get(groupSample(sliceName)).sample;
    },
});

const groupSampleQuery = graphQLSelectorFamily<
  VariablesOf<mainSampleQueryGraphQL>,
  SliceName,
  ResponseFrom<mainSampleQueryGraphQL>
>({
  environment: RelayEnvironmentKey,
  key: "mainSampleQuery",
  mapResponse: mapSampleResponse,
  query: mainSample,
  variables:
    (slice) =>
    ({ get }) => {
      return {
        view: get(view),
        dataset: get(dataset).name,
        filter: {
          group: {
            slice: slice ?? get(groupSlice(true)),
            id: get(modal).sample[get(groupField)]._id,
          },
        },
      };
    },
});

export const groupSample = selectorFamily<SampleData, SliceName>({
  key: "mainGroupSample",
  get:
    (sliceName) =>
    ({ get }) => {
      if (sliceName) {
        return get(groupSampleQuery(sliceName));
      }

      const field = get(groupField);
      const group = get(isGroup);

      const sample = get(modal);

      if (!field || !group) return sample;

      if (sample.sample[field].name === get(groupSlice(true))) {
        return sample;
      }

      return get(groupSampleQuery(sliceName));
    },
});

export const groupStatistics = atomFamily<"group" | "slice", boolean>({
  key: "groupStatistics",
  default: "slice",
});
