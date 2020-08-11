import React from "react";
import { Link } from "react-router-dom";
import styled from "styled-components";

export type Entry = {
  path: string;
  name: string;
};

export type Props = {
  entries: Entry[];
  currentPath: string;
};

const Body = styled.div`
  margin-top: 5px;
  margin-bottom: 5px;
`;

const Item = styled(Link)`
  display: inline-block;
  margin-right: 5px;
  padding: 0 1em;
  color: ${({ theme }) => theme.font};
  background-color: ${({ theme }) => theme.backgroundLight};
  text-decoration: none;
  font-weight: bold;
  text-transform: capitalize;

  &.active {
    background-color: ${({ theme }) => theme.secondary};
  }
`;

const HorizontalNav = ({ entries, currentPath }: Props) => {
  return (
    <Body>
      {entries.map((e) => (
        <Item
          key={e.path}
          to={e.path}
          className={e.path == currentPath ? "active" : ""}
        >
          {e.name}
        </Item>
      ))}
    </Body>
  );
};

export default HorizontalNav;
