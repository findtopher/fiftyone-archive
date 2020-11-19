import React from "react";
import { useRecoilValue } from "recoil";
import { Redirect } from "react-router-dom";

import routes from "../constants/routes.json";
import * as atoms from "../recoil/atoms";

function Loading() {
  const connected = useRecoilValue(atoms.connected);
  const loading = useRecoilValue(atoms.loading);

  if (!loading && connected) {
    return <Redirect to={routes.DATASET} />;
  } else if (!loading && !connected) {
    return <Redirect to={routes.SETUP} />;
  }
  return null;
}

export default Loading;
