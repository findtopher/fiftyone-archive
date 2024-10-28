import type { versionFragment$key } from "@fiftyone/relay";
import { graphQLSyncFragmentAtom, versionFragment } from "@fiftyone/relay";

export const version = graphQLSyncFragmentAtom<versionFragment$key, string>(
  { fragments: [versionFragment], read: (data) => data.version },
  {
    key: "version",
  }
);
