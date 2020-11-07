import React, { useContext, useEffect, useRef, useState } from "react";
import styled, { ThemeContext } from "styled-components";
import { useRecoilState, useRecoilValue, useSetRecoilState } from "recoil";
import { Machine, assign } from "xstate";
import { useMachine } from "@xstate/react";
import uuid from "uuid-v4";
import { animated, useSpring } from "react-spring";
import useMeasure from "react-use-measure";
import { Checkbox, FormControlLabel } from "@material-ui/core";

import * as atoms from "../recoil/atoms";
import * as selectors from "../recoil/selectors";
import { SampleContext } from "../utils/context";
import { useOutsideClick } from "../utils/hooks";
import SearchResults from "./ViewBar/ViewStage/SearchResults";
import { NamedRangeSlider } from "./RangeSlider";
import {
  CONFIDENCE_LABELS,
  OBJECT_TYPES,
  VALID_LIST_TYPES,
} from "../utils/labels";
import { removeObjectIDsFromSelection } from "../utils/selection";

const classFilterMachine = Machine({
  id: "classFilter",
  initial: "init",
  context: {
    error: undefined,
    classes: [],
    inputValue: "",
    selected: [],
    currentResult: null,
    errorId: null,
    results: [],
    prevValue: "",
  },
  states: {
    init: {},
    reading: {
      on: {
        EDIT: {
          target: "editing",
        },
      },
    },
    editing: {
      entry: [
        assign({
          currentResult: null,
          errorId: null,
          currentResult: null,
        }),
      ],
      type: "parallel",
      states: {
        input: {
          initial: "focused",
          states: {
            focused: {
              on: {
                UNFOCUS_INPUT: "unfocused",
              },
            },
            unfocused: {
              on: {
                FOCUS_INPUT: "focused",
              },
            },
          },
        },
        searchResults: {
          initial: "notHovering",
          states: {
            hovering: {
              on: {
                MOUSELEAVE: "notHovering",
              },
            },
            notHovering: {
              on: {
                MOUSEENTER: "hovering",
              },
            },
          },
        },
      },
      on: {
        NEXT_RESULT: {
          actions: assign({
            currentResult: ({ currentResult, results }) => {
              if (currentResult === null) return 0;
              return Math.min(currentResult + 1, results.length - 1);
            },
            inputValue: ({ currentResult, results }) => {
              if (currentResult === null) return results[0];
              return results[Math.min(currentResult + 1, results.length - 1)];
            },
          }),
        },
        PREVIOUS_RESULT: {
          actions: assign({
            currentResult: ({ currentResult }) => {
              if (currentResult === 0 || currentResult === null) return null;
              return currentResult - 1;
            },
            inputValue: ({ currentResult, prevValue, results }) => {
              if (currentResult === 0 || currentResult === null)
                return prevValue;
              return results[currentResult - 1];
            },
          }),
        },
        BLUR: {
          target: "reading",
        },
        COMMIT: [
          {
            actions: [
              assign({
                selected: ({ selected }, { value }) =>
                  [...new Set([...selected, value])].sort(),
                inputValue: "",
                valid: true,
              }),
            ],
            cond: ({ classes }, { value }) => {
              return classes.some((c) => c === value);
            },
          },
          {
            actions: assign({
              error: (_, { value }) => ({
                name: "label",
                error: `${value === "" ? '""' : value} does not exist`,
              }),
              errorId: uuid(),
              valid: false,
            }),
          },
        ],
        CHANGE: {
          actions: [
            assign({
              inputValue: (_, { value }) => value,
              results: ({ classes }, { value }) =>
                classes.filter((c) =>
                  c.toLowerCase().includes(value.toLowerCase())
                ),
              prevValue: ({ inputValue }) => inputValue,
            }),
          ],
        },
      },
    },
  },
  on: {
    CLEAR: {
      actions: [
        assign({
          selected: [],
        }),
      ],
    },
    REMOVE: {
      actions: [
        assign({
          selected: ({ selected }, { value }) => {
            return selected.filter((s) => s !== value);
          },
        }),
      ],
    },
    SET_CLASSES: {
      target: "reading",
      actions: [
        assign({
          classes: (_, { classes }) => (classes ? classes : []),
          results: ({ inputValue }, { classes }) =>
            classes
              ? classes.filter((c) =>
                  c.toLowerCase().includes(inputValue.toLowerCase())
                )
              : [],
        }),
      ],
    },
    SET_SELECTED: {
      actions: assign({
        selected: (_, { selected }) => selected,
      }),
    },
    SET_INVERT: {
      actions: assign({
        invert: (_, { invert }) => invert,
      }),
    },
  },
});

const FilterHeader = styled.div`
  display: flex;
  justify-content: space-between;

  a {
    cursor: pointer;
    text-decoration: underline;
  }
`;

const ClassInput = styled.input`
  width: 100%;
  background: ${({ theme }) => theme.backgroundDark};
  border: 1px solid #191c1f;
  box-shadow: 0 8px 15px 0 rgba(0, 0, 0, 0.43);
  border-radius: 2px;
  font-size: 14px;
  line-height: 1.2rem;
  font-weight: bold;
  padding: 0.5rem;
  margin-bottom: 0.5rem;

  &:focus {
    outline: none;
  }
`;

const Selected = styled.div`
  display: flex;
  justify-content: flex-start;
  margin: 0 -0.25rem;
  flex-wrap: wrap;
`;

const ClassButton = styled.button`
  background: ${({ theme }) => theme.background};
  border: 2px solid #393C3F;
  background-color: #2D3034;
  border-radius: 11px;
  text-align: center
  vertical-align: middle;
  margin: 0.5rem 0.25rem 0;
  padding: 0 0.5rem;
  line-height: 20px;
  font-weight: bold;
  cursor: pointer;
  &:focus {
    outline: none;
  }
`;

const ClassFilterContainer = styled.div`
  position: relative;
  margin: 0.25rem 0;
`;

const BoxedContainer = styled.div`
  background: ${({ theme }) => theme.backgroundDark};
  box-shadow: 0 8px 15px 0 rgba(0, 0, 0, 0.43);
  border: 1px solid #191c1f;
  border-radius: 2px;
  color: ${({ theme }) => theme.fontDark};
  margin-top: 0.25rem;
`;

const ClassFilter = ({ entry: { path, type, color }, atoms }) => {
  const theme = useContext(ThemeContext);
  const classes = useRecoilValue(selectors.labelClasses(path));
  const [selectedClasses, setSelectedClasses] = useRecoilState(
    atoms.includeLabels(path)
  );
  const [colorByLabel, setColorByLabel] = useRecoilState(
    atoms.colorByLabel(path)
  );
  const [state, send] = useMachine(classFilterMachine);
  const inputRef = useRef();

  useEffect(() => {
    send({ type: "SET_CLASSES", classes });
    setSelectedClasses(selectedClasses.filter((c) => classes.includes(c)));
  }, [classes]);

  useOutsideClick(inputRef, () => send("BLUR"));
  const { inputValue, results, currentResult, selected } = state.context;

  useEffect(() => {
    JSON.stringify(selected) !== JSON.stringify(selectedClasses) &&
      send({ type: "SET_SELECTED", selected: selectedClasses });
  }, [selectedClasses]);

  useEffect(() => {
    ((state.event.type === "COMMIT" && state.context.valid) ||
      state.event.type === "REMOVE" ||
      state.event.type === "CLEAR") &&
      setSelectedClasses(state.context.selected);
  }, [state.event]);

  return (
    <>
      <FilterHeader>
        Labels{" "}
        {selected.length ? (
          <a onClick={() => send({ type: "CLEAR" })}>clear {selected.length}</a>
        ) : null}
      </FilterHeader>
      <ClassFilterContainer>
        <div ref={inputRef}>
          <ClassInput
            value={inputValue}
            placeholder={"+ add label"}
            onFocus={() => state.matches("reading") && send("EDIT")}
            onBlur={() =>
              state.matches("editing.searchResults.notHovering") && send("BLUR")
            }
            onChange={(e) => send({ type: "CHANGE", value: e.target.value })}
            onKeyPress={(e) => {
              if (e.key === "Enter") {
                send({ type: "COMMIT", value: e.target.value });
              }
            }}
            onKeyDown={(e) => {
              switch (e.key) {
                case "Escape":
                  send("BLUR");
                  break;
                case "ArrowDown":
                  send("NEXT_RESULT");
                  break;
                case "ArrowUp":
                  send("PREVIOUS_RESULT");
                  break;
              }
            }}
          />
          {state.matches("editing") && (
            <SearchResults
              results={results.filter((r) => !selected.includes(r)).sort()}
              send={send}
              currentResult={currentResult}
              style={{
                position: "absolute",
                top: "0.25rem",
                fontSize: 14,
                maxHeight: 294,
                overflowY: "scroll",
              }}
            />
          )}
        </div>
        <Selected>
          {selected.map((s) => (
            <ClassButton
              key={s}
              onClick={() => {
                send({ type: "REMOVE", value: s });
              }}
            >
              {s + " "}
              <a style={{ color: theme.fontDark }}>x</a>
            </ClassButton>
          ))}
        </Selected>
        {OBJECT_TYPES.includes(type) && (
          <BoxedContainer>
            <FormControlLabel
              label={
                <div style={{ lineHeight: "20px", fontSize: 14 }}>
                  Color by label
                </div>
              }
              control={
                <Checkbox
                  checked={colorByLabel}
                  onChange={() => setColorByLabel(!colorByLabel)}
                  style={{
                    padding: "0 5px",
                    color: color,
                  }}
                />
              }
            />
          </BoxedContainer>
        )}
      </ClassFilterContainer>
    </>
  );
};

const CLS_TO_STAGE = {
  Classification: "FilterField",
  Classifications: "FilterClassifications",
  Detection: "FilterField",
  Detections: "FilterDetections",
  Polyline: "FilterField",
  Polylines: "FilterPolylines",
  Keypoint: "FilterField",
  Keypoints: "FilterKeypoints",
};

const makeFilter = (fieldName, cls, labels, range, includeNone, hasBounds) => {
  let fieldStr = VALID_LIST_TYPES.includes(cls) ? "$$this" : `$${fieldName}`;
  const confidenceStr = `${fieldStr}.confidence`;
  const labelStr = `${fieldStr}.label`;
  let rangeExpr = null;
  if (hasBounds) {
    rangeExpr = {
      $and: [
        { $gte: [confidenceStr, range[0]] },
        { $lte: [confidenceStr, range[1]] },
      ],
    };
  }
  if (includeNone && hasBounds) {
    rangeExpr = { $or: [rangeExpr, { $eq: [confidenceStr, null] }] };
  } else if (hasBounds) {
    rangeExpr = {
      $or: [rangeExpr, confidenceStr, { $eq: [confidenceStr, null] }],
    };
  } else if (!includeNone) {
    rangeExpr = { $or: [confidenceStr, { $eq: [confidenceStr, null] }] };
  }
  const labelsExpr = { $in: [labelStr, labels] };
  return {
    kwargs: [
      ["field", fieldName],
      [
        "filter",
        labels.length && rangeExpr
          ? { $and: [labelsExpr, rangeExpr] }
          : rangeExpr
          ? rangeExpr
          : labelsExpr,
      ],
    ],
    _cls: `fiftyone.core.stages.${CLS_TO_STAGE[cls]}`,
  };
};

const HiddenObjectFilter = ({ entry }) => {
  const fieldName = entry.name;
  const sample = useContext(SampleContext);
  const [hiddenObjects, setHiddenObjects] = useRecoilState(atoms.hiddenObjects);
  if (!sample) {
    return null;
  }

  const sampleHiddenObjectIDs = Object.entries(hiddenObjects)
    .filter(
      ([object_id, data]) =>
        data.sample_id === sample._id && data.field === fieldName
    )
    .map(([object_id]) => object_id);
  if (!sampleHiddenObjectIDs.length) {
    return null;
  }
  const clear = () =>
    setHiddenObjects((hiddenObjects) =>
      removeObjectIDsFromSelection(hiddenObjects, sampleHiddenObjectIDs)
    );

  return (
    <FilterHeader>
      Manually hidden: {sampleHiddenObjectIDs.length}
      <a onClick={clear}>reset</a>
    </FilterHeader>
  );
};

const Filter = React.memo(({ expanded, style, entry, modal, ...rest }) => {
  const socket = useRecoilValue(selectors.socket);
  const [range, setRange] = useRecoilState(rest.confidenceRange(entry.path));
  const [includeNone, setIncludeNone] = useRecoilState(
    rest.includeNoConfidence(entry.path)
  );

  const bounds = useRecoilValue(rest.confidenceBounds(entry.path));
  const [labels, setLabels] = useRecoilState(rest.includeLabels(entry.path));
  const fieldIsFiltered = useRecoilValue(rest.fieldIsFiltered(entry.path));
  const setExtendedDatasetStats = useSetRecoilState(atoms.extendedDatasetStats);

  const [stateDescription, setStateDescription] = useRecoilState(
    atoms.stateDescription
  );
  const filterStage = useRecoilValue(selectors.filterStage(entry.path));
  useEffect(() => {
    if (filterStage) return;
    setLabels([]);
    setIncludeNone(true);
    setRange([
      0 < bounds[0] && bounds[0] !== bounds[1] ? 0 : bounds[0],
      1 > bounds[1] && bounds[0] !== bounds[1] ? 1 : bounds[1],
    ]);
  }, [filterStage]);
  const hasBounds = bounds.every((b) => b !== null);
  const [overflow, setOverflow] = useState("hidden");

  useEffect(() => {
    hasBounds &&
      range.every((r) => r === null) &&
      setRange([
        0 < bounds[0] && bounds[0] !== bounds[1] ? 0 : bounds[0],
        1 > bounds[1] && bounds[0] !== bounds[1] ? 1 : bounds[1],
      ]);
  }, [bounds]);

  const [ref, { height }] = useMeasure();
  const props = useSpring({
    height: expanded ? height : 0,
    from: {
      height: 0,
    },
    onStart: () => !expanded && setOverflow("hidden"),
    onRest: () => expanded && setOverflow("visible"),
  });

  if (!modal) {
    useEffect(() => {
      const newState = JSON.parse(JSON.stringify(stateDescription));
      if (!fieldIsFiltered && !(entry.name in newState.filters)) return;
      setExtendedDatasetStats([]);
      const filter = makeFilter(
        entry.path,
        entry.type,
        labels,
        range,
        includeNone,
        hasBounds
      );
      if (
        JSON.stringify(filter) === JSON.stringify(newState.filters[entry.path])
      )
        return;
      if (!fieldIsFiltered && entry.path in newState.filters) {
        delete newState.filters[entry.path];
      } else {
        newState.filters[entry.path] = filter;
      }
      setStateDescription(newState);
      socket.emit("update", {
        data: newState,
        include_self: false,
      });
      const extendedView = [...(newState.view || [])];
      for (const stage in newState.filters) {
        extendedView.push(newState.filters[stage]);
      }
      socket.emit("get_statistics", extendedView, (data) => {
        setExtendedDatasetStats(data);
      });
    }, [bounds, range, includeNone, labels, fieldIsFiltered]);
  }

  return (
    <animated.div style={{ ...props, overflow }}>
      <div ref={ref}>
        <div style={{ margin: 3 }}>
          <ClassFilter entry={entry} atoms={rest} />
          <HiddenObjectFilter entry={entry} />
          {CONFIDENCE_LABELS.includes(entry.type) && (
            <NamedRangeSlider
              color={entry.color}
              name={"Confidence"}
              valueName={"confidence"}
              includeNoneAtom={rest.includeNoConfidence(entry.path)}
              boundsAtom={rest.confidenceBounds(entry.path)}
              rangeAtom={rest.confidenceRange(entry.path)}
              maxMin={0}
              minMax={1}
            />
          )}
        </div>
      </div>
    </animated.div>
  );
});

export default Filter;
