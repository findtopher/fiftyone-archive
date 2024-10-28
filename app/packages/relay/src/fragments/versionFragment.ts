import { graphql } from "react-relay";

export default graphql`
  fragment versionFragment on Query {
    version
  }
`;
