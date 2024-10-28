/**
 * @generated SignedSource<<e9aa5d366fa6b63db433012e87b824f5>>
 * @lightSyntaxTransform
 * @nogrep
 */

/* tslint:disable */
/* eslint-disable */
// @ts-nocheck

import { Fragment, ReaderFragment } from 'relay-runtime';
import { FragmentRefs } from "relay-runtime";
export type versionFragment$data = {
  readonly version: string;
  readonly " $fragmentType": "versionFragment";
};
export type versionFragment$key = {
  readonly " $data"?: versionFragment$data;
  readonly " $fragmentSpreads": FragmentRefs<"versionFragment">;
};

const node: ReaderFragment = {
  "argumentDefinitions": [],
  "kind": "Fragment",
  "metadata": null,
  "name": "versionFragment",
  "selections": [
    {
      "alias": null,
      "args": null,
      "kind": "ScalarField",
      "name": "version",
      "storageKey": null
    }
  ],
  "type": "Query",
  "abstractKey": null
};

(node as any).hash = "953186ab9980f7e93c1038d1a2dc6418";

export default node;
