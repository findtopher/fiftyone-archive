import React, { useState, useContext } from "react";
import styled, { ThemeContext } from "styled-components";
import { useRecoilValue, useSetRecoilState } from "recoil";

import {
  Autorenew,
  BarChart,
  Help,
  Label,
  PhotoLibrary,
} from "@material-ui/icons";

import CellHeader from "./CellHeader";
import CheckboxGrid from "./CheckboxGrid";
import DropdownCell from "./DropdownCell";
import SelectionTag from "./Tags/SelectionTag";
import { Button, scrollbarStyles } from "./utils";
import * as atoms from "../recoil/atoms";
import * as selectors from "../recoil/selectors";
import { refreshColorMap as refreshColorMapSelector } from "../recoil/selectors";
import { labelTypeHasColor } from "../utils/labels";

export type Entry = {
  name: string;
  selected: boolean;
  count: number;
  type: string;
  path: string;
};

type Props = {
  tags: Entry[];
  labels: Entry[];
  frameLabels: Entry[];
  scalars: Entry[];
  unsupported: Entry[];
  onSelectTag: (entry: Entry) => void;
};

const Container = styled.div`
  height: 100%;
  ${scrollbarStyles};

  .MuiCheckbox-root {
    padding: 4px 8px 4px 4px;
  }

  ${CellHeader.Body} {
    display: flex;
    align-items: center;
    color: ${({ theme }) => theme.fontDark};

    * {
      display: flex;
    }

    .label {
      text-transform: uppercase;
    }

    ${SelectionTag.Body} {
      float: right;
    }

    .push {
      margin-left: auto;
    }
    .icon {
      margin-left: 2px;
    }
  }

  .left-icon {
    margin-right: 4px;
  }
`;

const Cell = ({
  label,
  icon,
  entries,
  headerContent = null,
  onSelect,
  colorMap,
  title,
  modal,
  prefix = "",
}) => {
  const theme = useContext(ThemeContext);
  const [expanded, setExpanded] = useState(true);
  const numSelected = entries.filter((e) => e.selected).length;
  const handleClear = (e) => {
    if (!onSelect) {
      return;
    }
    e.stopPropagation();
    for (const entry of entries) {
      if (entry.selected) {
        onSelect({ ...entry, selected: false });
      }
    }
  };

  return (
    <DropdownCell
      label={
        <>
          {icon ? <span className="left-icon">{icon}</span> : null}
          <span className="label">{label}</span>
          <span className="push" />
          {numSelected ? (
            <SelectionTag
              count={numSelected}
              title="Clear selection"
              onClear={handleClear}
              onClick={handleClear}
            />
          ) : null}
        </>
      }
      title={title}
      expanded={expanded}
      onExpand={setExpanded}
    >
      {headerContent}
      {entries.length ? (
        <CheckboxGrid
          columnWidths={[3, 2]}
          entries={entries.map((e) => ({
            name: e.name,
            selected: e.selected,
            type: e.type,
            data: e.icon ? e.icon : [makeData(e.filteredCount, e.totalCount)],
            totalCount: e.totalCount,
            filteredCount: e.filteredCount,
            color: labelTypeHasColor(e.type)
              ? colorMap[prefix + e.name]
              : theme.backgroundLight,
            hideCheckbox: e.hideCheckbox,
            disabled: Boolean(e.disabled),
            path: prefix + e.name,
          }))}
          onCheck={onSelect}
          modal={modal}
          prefix={prefix}
        />
      ) : (
        <span>No options available</span>
      )}
    </DropdownCell>
  );
};

const makeCount = (count) => {
  return (count || 0).toLocaleString();
};

const makeData = (filteredCount, totalCount) => {
  if (typeof filteredCount === "number" && filteredCount !== totalCount) {
    return `${makeCount(filteredCount)} of ${makeCount(totalCount)}`;
  }
  return makeCount(totalCount);
};

const DisplayOptionsSidebar = React.forwardRef(
  (
    {
      modal = false,
      tags = [],
      labels = [],
      frameLabels = [],
      scalars = [],
      unsupported = [],
      onSelectTag,
      onSelectLabel,
      onSelectFrameLabel,
      onSelectScalar,
      headerContent = {},
      ...rest
    }: Props,
    ref
  ) => {
    const refreshColorMap = useSetRecoilState(refreshColorMapSelector);
    const colorMap = useRecoilValue(atoms.colorMap);
    const cellRest = { modal };
    const mediaType = useRecoilValue(selectors.mediaType);
    const isVideo = mediaType === "video";
    return (
      <Container ref={ref} {...rest}>
        <Cell
          colorMap={colorMap}
          label="Tags"
          icon={<PhotoLibrary />}
          entries={tags}
          headerContent={headerContent.tags}
          onSelect={onSelectTag}
          {...cellRest}
        />
        <Cell
          colorMap={colorMap}
          label="Labels"
          icon={<Label style={{ transform: "rotate(180deg)" }} />}
          entries={labels}
          headerContent={headerContent.labels}
          onSelect={onSelectLabel}
          {...cellRest}
        />
        {isVideo && (
          <Cell
            colorMap={colorMap}
            label="Frame Labels"
            icon={<PhotoLibrary />}
            entries={frameLabels}
            onSelect={onSelectFrameLabel}
            {...cellRest}
            prefix="frames."
          />
        )}
        <Cell
          colorMap={colorMap}
          label="Scalars"
          icon={<BarChart />}
          entries={scalars}
          headerContent={headerContent.scalars}
          onSelect={onSelectScalar}
          {...cellRest}
        />
        {unsupported.length ? (
          <Cell
            label="Unsupported"
            title="These fields cannot currently be displayed in the app"
            icon={<Help />}
            colorMap={{}}
            entries={unsupported.map((entry) => ({
              ...entry,
              selected: false,
              disabled: true,
            }))}
            headerContent={headerContent.unsupported}
            {...cellRest}
          />
        ) : null}
        {tags.length || labels.length || scalars.length ? (
          <Button onClick={refreshColorMap}>
            <Autorenew />
            Refresh colors
          </Button>
        ) : null}
        <div style={{ height: "1rem", width: "100%" }} />
      </Container>
    );
  }
);

export default DisplayOptionsSidebar;
