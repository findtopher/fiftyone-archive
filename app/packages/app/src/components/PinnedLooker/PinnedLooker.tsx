import React, { Suspense, useEffect } from "react";
import styled from "styled-components";

import { Resizable } from "re-resizable";

import { useTheme } from "@fiftyone/components";
import {
  PreloadedQuery,
  usePreloadedQuery,
  useRefetchableFragment,
} from "react-relay";
import {
  paginateGroupPinnedSample_query$key,
  paginateGroup,
  paginateGroupQuery,
  paginateGroupPinnedSampleFragment,
} from "@fiftyone/relay";
import * as fos from "@fiftyone/state";
import _ from "lodash";

const Container = styled.div`
  position: relative;

  height: 100%;
  width: 100%;
`;
import { useActivePlugins, PluginComponentType } from "@fiftyone/plugins";
import { useRecoilState, useRecoilValue } from "recoil";
import SidebarSourceSelector from "../SidebarSourceSelector";

function usePinnedVisualizerPlugin(
  fragmentRef: paginateGroupPinnedSample_query$key
) {
  const [resolvedSample, setResolvedSample] = useRecoilState(
    fos.resolvedPinnedSample
  );
  const [{ sample: sampleData }, refetch] = useRefetchableFragment(
    paginateGroupPinnedSampleFragment,
    fragmentRef
  );
  const sample = sampleData?.sample;

  useEffect(() => {
    setResolvedSample(sample);
  }, [sample]);
  const dataset = useRecoilValue(fos.dataset);
  const [visualizerPlugin] = useActivePlugins(PluginComponentType.Visualizer, {
    dataset,
    sample,
    pinned: true,
  });

  const slice = _.get(sample, [dataset.groupField, "name"].join("."), null);

  return {
    Visualizer: visualizerPlugin.component,
    slice,
    sample,
  };
}

const LookerContainer: React.FC<{
  fragmentRef: paginateGroupPinnedSample_query$key;
}> = ({ fragmentRef }) => {
  const { Visualizer, slice, sample } = usePinnedVisualizerPlugin(fragmentRef);

  if (!Visualizer) return null;
  return (
    <SidebarSourceSelector id="pinned" slice={slice} groupMode={true}>
      <Visualizer sampleOverride={sample} />
    </SidebarSourceSelector>
  );
};

const PinnedLooker: React.FC<
  React.PropsWithChildren<{
    queryRef: PreloadedQuery<paginateGroupQuery>;
  }>
> = ({ children, queryRef }) => {
  const theme = useTheme();
  const data = usePreloadedQuery(paginateGroup, queryRef);

  const [width, setWidth] = React.useState(400);
  const shown = true;
  return (
    <Resizable
      size={{ height: "100%", width }}
      minWidth={200}
      maxWidth={600}
      enable={{
        top: false,
        right: true,
        bottom: false,
        left: true,
        topRight: false,
        bottomRight: false,
        bottomLeft: false,
        topLeft: false,
      }}
      onResizeStop={(e, direction, ref, { width: delta }) => {
        setWidth(width + delta);
      }}
      style={{
        borderRight: `1px solid ${theme.backgroundDarkBorder}`,
      }}
    >
      <Container>
        <Suspense>
          <LookerContainer fragmentRef={data} />
        </Suspense>
      </Container>
    </Resizable>
  );
};

export default React.memo(PinnedLooker);
