import { useLayoutEffect, useMemo, useState } from "react";
import type { ID } from "@fiftyone/spotlight";
import Spotlight from "@fiftyone/spotlight";
import type { Lookers } from "@fiftyone/state";
import * as fos from "@fiftyone/state";
import { v4 as uuid } from "uuid";
import { Box, Slider, Typography } from "@mui/material";

/**
 * Type definitions for convenience and consistency.
 *
 * Some of these types are partially defined in other places, but these
 * definitions are specific to the data being processed in this component.
 */

/**
 * Generic sample data.
 */
type Sample = {
  filepath: string;
  [k: string]: any;
};

/**
 * URLs type encapsulated in other types.
 */
type SampleUrls = {
  filepath: string;
};

/**
 * Sample metadata expected by the Spotlight.
 */
type SampleMetadata = {
  key: number;
  aspectRatio: number;
  id: {
    description: string;
  };
  data: {
    id: string;
    sample: Sample & {
      _id: string;
    };
    urls: SampleUrls;
  };
};

/**
 * Page of samples used by the Spotlight.
 */
type SamplePage = {
  items: SampleMetadata[];
  next: number | null;
  previous: number | null;
};

/**
 * Sample metadata expected by the Looker.
 */
type SampleStoreEntry = {
  aspectRatio: number;
  id: string;
  sample: Sample;
  urls: SampleUrls;
};

/**
 * Minimum zoom level for rendered samples.
 */
const minZoomLevel = 1;

/**
 * Maximum zoom level for rendered samples.
 */
const maxZoomLevel = 11;

/**
 * Component which handles rendering samples.
 *
 * This component makes use of the Spotlight and Looker components, which
 * do the heavy lifting of actually rendering the samples.
 */
export const Lens = ({
  samples,
  sampleSchema,
}: {
  samples: Sample[];
  sampleSchema: object;
}) => {
  const elementId = useMemo(() => uuid(), []);
  const lookerStore = useMemo(() => new WeakMap<ID, Lookers>(), []);
  const sampleStore = useMemo(() => new WeakMap<ID, SampleStoreEntry>(), []);

  // Use the same looker options as the Grid as a starting point.
  const baseOpts = fos.useLookerOptions(false);

  // Augment the looker options with data specific to this component.
  const lookerOpts = useMemo(() => {
    // Detect presence of labels
    const labelFields = new Set<string>();
    samples.forEach((sample) => {
      for (let key of Object.keys(sample)) {
        if (sample[key] instanceof Object) {
          // If this sample field has a '_cls' attribute, then
          //   we assume this is a label.
          if (Object.keys(sample[key]).find((k) => k === "_cls")) {
            labelFields.add(key);
          }
        }
      }
    });

    return {
      ...baseOpts,
      // Render all labels
      filter: () => true,
      activePaths: Array.from(labelFields.values()),
    };
  }, [samples, baseOpts]);

  // Generate a valid field schema for use by the looker.
  const cleanedSchema = useMemo(() => {
    // Helper method for converting from snake_case to camelCase
    const toCamelCase = (str: string): string => {
      const s = str
        .match(
          /[A-Z]{2,}(?=[A-Z][a-z]+[0-9]*|\b)|[A-Z]?[a-z]+[0-9]*|[A-Z]|[0-9]+/g
        )
        ?.map(
          (x: string) => x.slice(0, 1).toUpperCase() + x.slice(1).toLowerCase()
        )
        .join("");
      return s && s.slice(0, 1).toLowerCase() + s.slice(1);
    };

    // The schema returned by the SDK needs to be massaged for the looker
    //   to render properly.
    // This method achieves the following:
    //   1. Convert keys from snake_case to camelCase
    //   2. Convert the 'fields' property from an array to a nested object
    //   3. Ensure 'path' is available as a top-level property
    //   4. Do (1) - (3) recursively for nested objects
    const formatSchema = (schema: object) => {
      const formatted = {};

      // Convert top-level keys to camelCase
      for (let k of Object.keys(schema)) {
        formatted[toCamelCase(k)] = schema[k];
      }

      // Ensure 'path' is defined
      formatted["path"] = schema["name"];

      // 'fields' is formatted as an array, but looker expects this
      //   to be a nested object instead.
      if (formatted["fields"] instanceof Array) {
        const remapped = {};
        for (let subfield of formatted["fields"]) {
          // Recurse for each nested object
          remapped[subfield["name"]] = formatSchema(subfield);
        }
        formatted["fields"] = remapped;
      }

      return formatted;
    };

    const formattedSchema = {};
    for (let k of Object.keys(sampleSchema)) {
      if (sampleSchema[k] instanceof Object) {
        formattedSchema[k] = formatSchema(sampleSchema[k]);
        formattedSchema[k]["path"] = sampleSchema[k]["name"];
      } else {
        formattedSchema[k] = sampleSchema[k];
      }
    }

    return formattedSchema;
  }, [sampleSchema]);

  const createLooker = fos.useCreateLooker(
    false,
    true,
    lookerOpts,
    undefined,
    undefined,
    cleanedSchema
  );
  const [resizing, setResizing] = useState(false);
  const [zoom, setZoom] = useState(
    Math.floor((minZoomLevel + maxZoomLevel) / 2)
  );

  const spotlight = useMemo(() => {
    if (resizing) {
      return;
    }

    return new Spotlight<number, fos.Sample>({
      key: 0, // initial page index
      scrollbar: true,
      rowAspectRatioThreshold: (width: number) => {
        let min = 1;
        if (width >= 1200) {
          min = -5;
        } else if (width >= 1000) {
          min = -3;
        } else if (width >= 800) {
          min = -1;
        }

        return Math.max(minZoomLevel, maxZoomLevel - Math.max(min, zoom));
      },
      get: (page: number): Promise<SamplePage> => {
        // In this implementation, we only support a single page, which
        //   is the collection of samples passed in through props.
        const mappedSamples: SampleMetadata[] = samples.map((s) => {
          const id = uuid();
          return {
            key: 0,
            aspectRatio: 1,
            id: {
              description: id,
            },
            data: {
              id,
              sample: {
                _id: id,
                ...s,
              },
              urls: {
                filepath: s.filepath,
              },
            },
          };
        });

        // Store these samples in the sample store; this is where the renderer will pull from
        mappedSamples.forEach((s) => {
          const storeElement: SampleStoreEntry = {
            aspectRatio: 1,
            id: s.id.description,
            sample: s.data.sample,
            urls: s.data.urls,
          };

          sampleStore.set(s.id, storeElement);
        });

        return Promise.resolve({
          items: mappedSamples,
          next: null,
          previous: null,
        });
      },
      render: (
        id: ID,
        element: HTMLDivElement,
        dimensions: [number, number],
        soft: boolean,
        disable: boolean
      ) => {
        if (lookerStore.has(id)) {
          const looker = lookerStore.get(id);
          if (disable) {
            looker?.disable();
          } else {
            looker?.attach(element, dimensions);
          }
          return;
        }

        const sample = sampleStore.get(id);

        if (!(createLooker.current && sample)) {
          throw new Error(
            `createLooker=${!!createLooker.current}, sample=${JSON.stringify(
              sample
            )}`
          );
        }

        const init = (looker: Lookers) => {
          lookerStore.set(id, looker);
          looker.attach(element, dimensions);
        };

        if (!soft) {
          init(createLooker.current({ ...sample, symbol: id }));
        }
      },
      spacing: 20,
    });
  }, [lookerStore, sampleStore, createLooker, samples, resizing, zoom]);

  // Attach spotlight to this component's root element
  useLayoutEffect(() => {
    if (!spotlight || resizing) {
      return;
    }

    const element = document.getElementById(elementId);
    if (element) {
      spotlight.attach(element);
    }

    return () => {
      spotlight.destroy();
    };
  }, [elementId, spotlight, resizing]);

  // Register resize observer to trigger re-render
  useLayoutEffect(() => {
    const el = () => document.getElementById(elementId)?.parentElement;
    const observer = new ResizeObserver(() => {
      setResizing(true);
      setTimeout(() => setResizing(false), 100);
    });

    const element = el();
    element && observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, [elementId]);

  return (
    <Box>
      {/*Controls*/}
      <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
        <Box sx={{ flex: "0 1 200px", mb: 2 }}>
          <Typography color="secondary" gutterBottom>
            Zoom level
          </Typography>
          <Slider
            value={zoom}
            onChange={(_, val) => setZoom(val instanceof Array ? val[0] : val)}
            min={minZoomLevel}
            max={maxZoomLevel}
            step={1}
            color="primary"
          />
        </Box>
      </Box>

      {/*Spotlight container*/}
      <Box
        sx={{
          width: "100%",
          height: "800px",
        }}
      >
        {/*Spotlight*/}
        <Box id={elementId} sx={{ width: "100%", height: "100%" }}></Box>
      </Box>
    </Box>
  );
};
