import React, { useContext, useEffect, useRef, useState } from "react";
import { animated, useSpring } from "react-spring";
import styled, { ThemeContext } from "styled-components";
import { useService } from "@xstate/react";
import { ReportProblem, VerticalAlignBottom } from "@material-ui/icons";

import { useOutsideClick } from "../../../utils/hooks";

const ErrorMessageDiv = animated(styled.div`
  box-sizing: border-box;
  border-radius: 3px;
  background-color: #191c1f;
  box-shadow: 0 2px 25px 0 rgba(0, 0, 0, 0.16);
  color: ${({ theme }) => theme.fontDark};
  border-radius: 2px;
  padding: 0.5rem;
  line-height: 1rem;
  margin-top: 2.5rem;
  font-weight: bold;
  position: fixed;
  width: auto;
  z-index: 800;
`);

const ErrorHeader = styled.div`
  color: ${({ theme }) => theme.font};
  display: flex;
  padding-bottom: 0.5rem;
`;

const ErrorMessage = React.memo(({ serviceRef, style }) => {
  const theme = useContext(ThemeContext);
  const [state, send] = useService(serviceRef);
  const ref = useRef();
  const [errorTimeout, setErrorTimeout] = useState(null);
  const { error, errorId } = state.context;
  const animations = useSpring({
    opacity: errorId ? 1 : 0,
    from: {
      opacity: 0,
    },
  });

  useEffect(() => {
    errorTimeout && clearTimeout(errorTimeout);
    !errorId && setErrorTimeout(setTimeout(() => send("CLEAR_ERROR"), 1000));
  }, [errorId]);

  useOutsideClick(ref, () => send("CLEAR_ERROR_ID"));

  return (
    <ErrorMessageDiv
      ref={ref}
      style={{ ...animations, display: error ? "block" : "none", ...style }}
    >
      {error ? (
        <>
          <ErrorHeader>
            <ReportProblem
              style={{ color: theme.error, marginRight: "0.5rem" }}
            />
            <div
              style={{ marginTop: "0.25rem" }}
            >{`Invalid ${error.name}.`}</div>
          </ErrorHeader>
          {error.error}
        </>
      ) : null}
    </ErrorMessageDiv>
  );
});

export default ErrorMessage;
