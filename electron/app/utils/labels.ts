export const VALID_OBJECT_TYPES = [
  "Detection",
  "Detections",
  "Keypoint",
  "Keypoints",
  "Polyline",
  "Polylines",
];
export const VALID_CLASS_TYPES = ["Classification", "Classifications"];
export const VALID_MASK_TYPES = ["Segmentation"];
export const VALID_LIST_TYPES = [
  "Classifications",
  "Detections",
  "Keypoints",
  "Polylines",
];
export const VALID_LABEL_TYPES = [
  ...VALID_CLASS_TYPES,
  ...VALID_OBJECT_TYPES,
  ...VALID_MASK_TYPES,
];

export const FILTERABLE_TYPES = [
  "Classification",
  "Classifications",
  "Detection",
  "Detections",
];

export const VALID_SCALAR_TYPES = [
  "fiftyone.core.fields.BooleanField",
  "fiftyone.core.fields.FloatField",
  "fiftyone.core.fields.IntField",
  "fiftyone.core.fields.StringField",
];

export const VALID_NUMERIC_TYPES = [
  "fiftyone.core.fields.FloatField",
  "fiftyone.core.fields.IntField",
];

export const RESERVED_FIELDS = [
  "metadata",
  "media_type",
  "_id",
  "tags",
  "filepath",
  "frames",
  "frame_number",
];
export const RESERVED_DETECTION_FIELDS = [
  "label",
  "index",
  "bounding_box",
  "confidence",
  "attributes",
  "mask",
];

export const METADATA_FIELDS = [
  { name: "Size (bytes)", key: "size_bytes" },
  { name: "Type", key: "mime_type" },
  { name: "Media type", key: "media_type" },
  {
    name: "Dimensions",
    value: (metadata) => {
      if (!isNaN(metadata.width) && !isNaN(metadata.height)) {
        return `${metadata.width} x ${metadata.height}`;
      }
    },
  },
  { name: "Channels", key: "num_channels" },
];

export const stringify = (value) => {
  if (typeof value == "number") {
    value = Number(value.toFixed(3));
  }
  return String(value);
};

export const labelTypeHasColor = (labelType) => {
  return !VALID_MASK_TYPES.includes(labelType);
};

export const labelTypeIsFilterable = (labelType) => {
  return FILTERABLE_TYPES.includes(labelType);
};

export const getLabelText = (label) => {
  if (
    !label._cls ||
    !(
      VALID_LABEL_TYPES.includes(label._cls) ||
      VALID_SCALAR_TYPES.includes(label._cls)
    ) ||
    VALID_OBJECT_TYPES.includes(label._cls)
  ) {
    return undefined;
  }
  let value = undefined;
  for (const prop of ["label", "value"]) {
    if (label.hasOwnProperty(prop)) {
      value = label[prop];
      break;
    }
  }
  if (value === undefined) {
    return undefined;
  }
  return stringify(value);
};

export const formatMetadata = (metadata) => {
  if (!metadata) {
    return [];
  }
  return METADATA_FIELDS.map((field) => ({
    name: field.name,
    value: field.value ? field.value(metadata) : metadata[field.key],
  })).filter(({ value }) => value !== undefined);
};

export function makeLabelNameGroups(
  mediaType,
  fieldSchema,
  labelNames,
  labelTypes
) {
  const labelNameGroups = {
    labels: [],
    scalars: [],
    unsupported: [],
  };
  const frameLabelNameGroups = {
    labels: [],
    scalars: [],
    unsupported: [],
  };

  for (let i = 0; i < labelNames.length; i++) {
    const name = labelNames[i];
    const type = labelTypes[i];
    if (RESERVED_FIELDS.includes(name)) {
      continue;
    } else if (VALID_LABEL_TYPES.includes(type)) {
      labelNameGroups.labels.push({ name, type });
    } else if (VALID_SCALAR_TYPES.includes(fieldSchema[name].ftype)) {
      labelNameGroups.scalars.push({ name });
    } else {
      labelNameGroups.unsupported.push({ name });
    }
  }
  return labelNameGroups;
}

export type Attrs = {
  [name: string]: {
    name: string;
    value: string;
  };
};

const _formatAttributes = (obj) =>
  Object.fromEntries(
    Object.entries(obj)
      .filter(
        ([key, value]) =>
          !key.startsWith("_") &&
          !RESERVED_DETECTION_FIELDS.includes(key) &&
          ["string", "number", "boolean"].includes(typeof value)
      )
      .map(([key, value]) => [key, stringify(value)])
  );

export const getDetectionAttributes = (detection: object): Attrs => {
  return {
    ..._formatAttributes(detection),
    ..._formatAttributes(
      Object.fromEntries(
        Object.entries(detection.attributes).map(([key, value]) => [
          key,
          value.value,
        ])
      )
    ),
  };
};

export const convertAttributesToETA = (attrs: Attrs): object[] => {
  return Object.entries(attrs).map(([name, value]) => ({ name, value }));
};

const FIFTYONE_TO_ETA_CONVERTERS = {
  Classification: {
    key: "attrs",
    convert: (name, obj) => {
      return {
        type: "eta.core.data.CategoricalAttribute",
        name,
        confidence: obj.confidence,
        value: obj.label,
      };
    },
  },
  Detection: {
    key: "objects",
    convert: (name, obj, frame_number) => {
      const bb = obj.bounding_box;
      const attrs = convertAttributesToETA(getDetectionAttributes(obj));
      const base = frame_number ? { frame_number } : {};
      return {
        ...base,
        type: "eta.core.objects.DetectedObject",
        name,
        label: obj.label,
        index: obj.index,
        confidence: obj.confidence,
        mask: obj.mask,
        bounding_box: bb
          ? {
              top_left: { x: bb[0], y: bb[1] },
              bottom_right: { x: bb[0] + bb[2], y: bb[1] + bb[3] },
            }
          : {
              top_left: { x: 0, y: 0 },
              bottom_right: { x: 0, y: 0 },
            },
        attrs: { attrs },
      };
    },
  },
  Keypoint: {
    key: "keypoints",
    convert: (name, obj) => {
      return {
        name,
        label: obj.label,
        points: obj.points,
      };
    },
  },
  Polyline: {
    key: "polylines",
    convert: (name, obj) => {
      return {
        name,
        label: obj.label,
        points: obj.points,
        closed: Boolean(obj.closed),
        filled: Boolean(obj.filled),
      };
    },
  },
};

const _addToETAContainer = (obj, key, item) => {
  if (!obj[key]) {
    obj[key] = {};
  }
  if (!obj[key][key]) {
    obj[key][key] = [];
  }
  obj[key][key].push(item);
};

export const convertSampleToETA = (sample, fieldSchema) => {
  if (sample.media_type === "image") {
    return convertImageSampleToETA(sample, fieldSchema);
  } else if (sample.media_type === "video") {
    let first_frame = {};
    if (sample.frames.first_frame) {
      first_frame = convertImageSampleToETA(
        sample.frames.first_frame,
        fieldSchema,
        1
      );
    }
    first_frame.frame_number = 1;
    return {
      frames: {
        1: first_frame,
      },
    };
  }
};

const convertImageSampleToETA = (sample, fieldSchema, frame_number) => {
  const imgLabels = {
    masks: [],
  };
  const sampleFields = Object.keys(sample).sort();
  for (const sampleField of sampleFields) {
    if (RESERVED_FIELDS.includes(sampleField)) {
      continue;
    }
    const field = sample[sampleField];
    if (field === null || field === undefined) continue;
    if (FIFTYONE_TO_ETA_CONVERTERS.hasOwnProperty(field._cls)) {
      const { key, convert } = FIFTYONE_TO_ETA_CONVERTERS[field._cls];
      _addToETAContainer(
        imgLabels,
        key,
        convert(sampleField, field, frame_number)
      );
    } else if (VALID_LIST_TYPES.includes(field._cls)) {
      for (const object of field[field._cls.toLowerCase()]) {
        const { key, convert } = FIFTYONE_TO_ETA_CONVERTERS[object._cls];
        _addToETAContainer(
          imgLabels,
          key,
          convert(sampleField, object, frame_number)
        );
      }
      continue;
    } else if (VALID_MASK_TYPES.includes(field._cls)) {
      imgLabels.masks.push({
        name: sampleField,
        mask: field.mask,
      });
    } else if (VALID_SCALAR_TYPES.includes(fieldSchema[sampleField])) {
      _addToETAContainer(imgLabels, "attrs", {
        name: sampleField,
        value: stringify(field),
      });
    }
  }
  return imgLabels;
};
