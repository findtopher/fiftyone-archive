import React from "react";
import styled from "styled-components";

export const Box = styled.div`
  padding: 1em;
  box-sizing: border-box;
  border: 2px solid ${({ theme }) => theme.border};
  background-color: ${({ theme }) => theme.background};
`;

export const VerticalSpacer = styled.div`
  height: ${({ height }) =>
    typeof height == "number" ? height + "px" : height};
  background-color: ${({ opaque, theme }) =>
    opaque ? theme.background : undefined};
`;

export const Button = styled.button`
  background-color: ${({ theme }) => theme.button};
  color: ${({ theme }) => theme.font};
  border: 1px solid ${({ theme }) => theme.buttonBorder};
  border-radius: 1px;
  margin: 0 3px;
  padding: 3px 10px;
  font-weight: bold;
  cursor: pointer;
`;

export const Overlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: ${({ theme }) => theme.overlay};
  z-index: 10000;
`;

export const ModalWrapper = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;

  > *:not(${Overlay}) {
    z-index: 10001;
  }
`;

export const ModalFooter = styled.footer`
  display: flex;
  flex-shrink: 0;
  border-top: 2px solid ${({ theme }) => theme.border};
  padding: 1em;
  background-color: ${({ theme }) => theme.backgroundLight};
`;
