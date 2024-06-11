import { Selector, UseSearch } from "@fiftyone/components";
import {
  datasetHeadName,
  datasetName,
  datasetSnapshotName,
  useSetDataset,
} from "@fiftyone/state";
import React, { useMemo } from "react";
import { useRecoilValue } from "recoil";

const DatasetLink: React.FC<{ value: string; className?: string }> = ({
  className,
  value,
}) => {
  return (
    <a className={className} title={value}>
      {value}
    </a>
  );
};

const DatasetSelector: React.FC<{
  useSearch: UseSearch<string>;
}> = ({ useSearch }) => {
  const setDataset = useSetDataset();
  const dataset = useRecoilValue(datasetName);
  const datasetHead = useRecoilValue(datasetHeadName);
  const datasetSnapshot = useRecoilValue(datasetSnapshotName);

  const nameWithSnapshot = useMemo(() => {
    if (datasetHead && datasetSnapshot) {
      return `${datasetHead} (${datasetSnapshot})`;
    }
  }, [datasetHead, datasetSnapshot]);

  return (
    <Selector<string>
      cy={"dataset"}
      component={DatasetLink}
      placeholder={"Select dataset"}
      inputStyle={{ height: 40, maxWidth: 300 }}
      containerStyle={{ position: "relative" }}
      onSelect={async (name) => {
        setDataset(name);
        return name;
      }}
      overflow={true}
      useSearch={useSearch}
      value={nameWithSnapshot || dataset || ""}
    />
  );
};

export default DatasetSelector;
