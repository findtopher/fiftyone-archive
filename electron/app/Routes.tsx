import React, { useState } from "react";
import { Switch, Route } from "react-router-dom";
import { useRecoilValue } from "recoil";

import routes from "./constants/routes.json";
import App from "./containers/App";
import Dataset from "./containers/Dataset";
import Setup from "./containers/Setup";
import Loading from "./containers/Loading";
import connect from "./utils/connect";
import * as atoms from "./recoil/atoms";

function Routes({ port }) {
  const [activeTags, setActiveTags] = useState({});
  const [activeLabels, setActiveLabels] = useState({});
  const [activeOther, setActiveOther] = useState({});
  const colors = useRecoilValue(atoms.colors);
  const appProps = {
    activeTags,
    setActiveTags,
    activeLabels,
    setActiveLabels,
    setActiveOther,
    activeOther,
    colors,
  };
  const datasetProps = {
    activeTags,
    activeLabels,
    activeOther,
    setActiveTags,
    setActiveLabels,
    setActiveOther,
    colors,
  };
  const dataset = (props) => {
    return <Dataset {...props} displayProps={datasetProps} />;
  };

  return (
    <App displayProps={appProps} colors={colors}>
      <Switch>
        <Route path={routes.LOADING} exact component={Loading} />
        <Route path={routes.SETUP} exact component={Setup} />
        <Route path={routes.SAMPLES} exact render={dataset} />
        <Route path={routes.LABELS} exact render={dataset} />
        <Route path={routes.TAGS} exact render={dataset} />
        <Route path={routes.SCALARS} exact render={dataset} />
        <Route path={routes.DATASET} render={dataset} />
      </Switch>
    </App>
  );
}

export default connect(Routes);
