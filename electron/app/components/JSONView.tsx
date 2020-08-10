import React, { useState, useRef } from "react";
import styled from "styled-components";
import copy from "copy-to-clipboard";

import { Button, ModalFooter } from "./utils";

type Props = {
  object: object;
};

const Body = styled.div`
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;

  pre {
    margin: 0;
    padding: 2em;
    flex-grow: 1;
    overflow-y: auto;
  }

  ${ModalFooter} {
    flex-direction: column;
    align-items: flex-end;
  }
`;

const JSONView = ({ object }: Props) => {
  const str = JSON.stringify(object, null, 4);
  return (
    <Body>
      <pre>{str}</pre>
      <ModalFooter>
        <Button onClick={() => copy(str)}>Copy JSON</Button>
      </ModalFooter>
    </Body>
  );
};

export default JSONView;
