import uuid from "uuid-v4";
import { Machine, actions, sendParent } from "xstate";
const { assign, cancel, send } = actions;

const convert = (v) => (typeof v !== "string" ? String(v) : v);

export const toTypeAnnotation = (type) => {
  if (type.includes("|")) {
    return [
      "Union[",
      type
        .split("|")
        .map((t) => toTypeAnnotation(t))
        .join(", "),
      "]",
    ].join("");
  } else if (type === "list<str>") {
    return "List[str]";
  } else if (type === "list<id>") {
    return "List[id]";
  } else return type;
};

/**
 * See https://stackoverflow.com/questions/175739/built-in-way-in-javascript-to-check-if-a-string-is-a-valid-number
 * for details about numbers and javascript
 */
export const PARSER = {
  NoneType: {
    castFrom: () => "None",
    castTo: () => null,
    parse: () => "None",
    validate: (value) => [null, "None", ""].some((v) => value === v),
  },
  bool: {
    castFrom: (value) => (value ? "True" : "False"),
    castTo: (value) => ["true", "false"].indexOf(value.toLowerCase()) === 0,
    parse: (value) => {
      return (
        value.toLowerCase().charAt(0).toUpperCase() +
        value.toLowerCase().slice(1)
      );
    },
    validate: (value) =>
      ["true", "false"].indexOf(convert(value).toLowerCase()) >= 0,
  },
  float: {
    castFrom: (value) => String(value),
    castTo: (value) => +value,
    parse: (value) => {
      const stripped = value.replace(/[\s]/g, "");
      const [integer, fractional] = stripped.split(".");
      return (
        integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",") +
        (fractional ? "." + fractional : "")
      );
    },
    validate: (value) => {
      const stripped = convert(value).replace(/[\s]/g, "");
      return stripped !== "" && !isNaN(+stripped);
    },
  },
  id: {
    castFrom: (value) => value,
    castTo: (value) => value,
    parse: (value) => value,
    validate: (value) => /[0-9A-Fa-f]{24}/g.test(value),
  },
  int: {
    castFrom: (value) => String(value),
    castTo: (value) => +value,
    parse: (value) =>
      value.replace(/[,\s]/g, "").replace(/\B(?=(\d{3})+(?!\d))/g, ","),
    validate: (value) => /^\d+$/.test(convert(value).replace(/[,\s]/g, "")),
  },
  "list<str>": {
    castFrom: (value) => {
      return value === "string" ? JSON.stringify(value) : value;
    },
    castTo: (value) => JSON.parse(value).map((e) => PARSER.str.castTo(e)),
    parse: (value) => {
      const array = JSON.parse(value);
      return JSON.stringify(array.map((e) => PARSER.str.parse(e)));
    },
    validate: (value) => {
      try {
        const array = typeof value === "string" ? JSON.parse(value) : value;
        return (
          Array.isArray(array) && array.every((e) => PARSER.str.validate(e))
        );
      } catch {
        return false;
      }
    },
  },
  "list<id>": {
    castFrom: (value) => {
      return JSON.stringify(value);
    },
    castTo: (value) =>
      typeof value === "string"
        ? JSON.parse(value).map((e) => PARSER.str.castTo(e))
        : value,
    parse: (value) => {
      const array = JSON.parse(value);
      return JSON.stringify(array.map((e) => PARSER.id.parse(e)));
    },
    validate: (value) => {
      try {
        const array = typeof value === "string" ? JSON.parse(value) : value;
        return (
          Array.isArray(array) && array.every((e) => PARSER.id.validate(e))
        );
      } catch {
        return false;
      }
    },
  },
  str: {
    castFrom: (value) => value,
    castTo: (value) => value,
    parse: (value) => value,
    validate: () => true,
  },
  dict: {
    castFrom: (value) => JSON.stringify(value),
    castTo: (value) => (typeof value === "string" ? JSON.parse(value) : value),
    parse: (value) => value,
    validate: (value) => {
      try {
        const v = typeof value === "string" ? JSON.parse(value) : value;
        return v instanceof Object && !Array.isArray(value);
      } catch {
        return false;
      }
    },
  },
};

export default Machine(
  {
    id: "viewStageParameter",
    initial: "decide",
    context: {
      id: undefined,
      defaultValue: undefined,
      parameter: undefined,
      stage: undefined,
      type: undefined,
      value: undefined,
      submitted: undefined,
      tail: undefined,
      focusOnInit: undefined,
      error: undefined,
    },
    states: {
      decide: {
        always: [
          {
            target: "editing",
            cond: (ctx) => ctx.focusOnInit,
          },
          {
            target: "reading.submitted",
            cond: (ctx) => ctx.submitted,
          },
          {
            target: "reading.pending",
          },
        ],
      },
      reading: {
        initial: "pending",
        entry: "blurInput",
        states: {
          pending: {},
          submitted: {},
        },
        on: {
          EDIT: "editing",
        },
      },
      editing: {
        entry: [
          sendParent("PARAMETER.EDIT"),
          assign({
            prevValue: ({ value }) => value,
            focusOnInit: false,
            value: ({ value }) =>
              PARSER.dict.validate(value)
                ? JSON.stringify(JSON.parse(value), null, 2)
                : value,
          }),
          "focusInput",
        ],
        on: {
          CHANGE: {
            actions: [
              assign({
                value: (_, { value }) => value,
                errorId: undefined,
              }),
            ],
          },
          COMMIT: [
            {
              target: "decide",
              actions: [
                assign({
                  submitted: true,
                  value: ({ type, value }) =>
                    type.split("|").reduce((acc, t) => {
                      const parser = PARSER[t];
                      return parser.validate(value) ? parser.parse(value) : acc;
                    }, undefined),
                  errorId: undefined,
                }),
                sendParent((ctx) => ({
                  type: "PARAMETER.COMMIT",
                  parameter: ctx,
                })),
              ],
              cond: ({ type, value }) => {
                return type.split("|").some((t) => PARSER[t].validate(value));
              },
            },
            {
              actions: [
                assign({
                  error: ({ type }) => ({
                    name: "value",
                    error: `Expected type "${toTypeAnnotation(type)}"`,
                  }),
                  errorId: uuid(),
                }),
              ],
            },
          ],
          CANCEL: {
            target: "reading.pending",
            actions: [
              assign({
                value: ({ prevValue }) => prevValue,
                errorId: undefined,
              }),
            ],
          },
        },
      },
    },
    on: {
      BLUR: [
        {
          target: "reading.pending",
          cond: ({ submitted, prevValue }) => !submitted && prevValue !== "",
          actions: [
            assign({
              value: ({ prevValue }) => prevValue,
            }),
          ],
        },
        {
          target: "reading.submitted",
          cond: ({ submitted }) => submitted,
        },
      ],
      CLEAR_ERROR: {
        actions: [
          assign({
            error: undefined,
          }),
        ],
      },
      CLEAR_ERROR_ID: {
        actions: [
          assign({
            errorId: undefined,
          }),
        ],
      },
    },
  },
  {
    actions: {
      blurInput: () => {},
      focusInput: () => {},
    },
  }
);
