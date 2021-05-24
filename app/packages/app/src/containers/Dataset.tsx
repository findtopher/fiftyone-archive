import React, { useEffect, useMemo, useRef } from "react";
import { useRecoilState, useRecoilValue } from "recoil";
import styled from "styled-components";

import SamplesContainer from "./SamplesContainer";
import HorizontalNav from "../components/HorizontalNav";
import SampleModal from "../components/SampleModal";
import { ModalWrapper } from "../components/utils";
import * as atoms from "../recoil/atoms";
import * as selectors from "../recoil/selectors";
import {
  useOutsideClick,
  useSendMessage,
  useScreenshot,
  useSampleUpdate,
  useGA,
} from "../utils/hooks";
import Loading from "../components/Loading";
import { useClearModal } from "../recoil/utils";

const PLOTS = ["Sample tags", "Label tags", "Labels", "Scalars"];

const Container = styled.div`
  height: calc(100% - 74px);
  display: flex;
  flex-direction: column;
`;

const Body = styled.div`
  padding: 0 1rem;
  width: 100%;
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
`;

function Dataset() {
  const [modal, setModal] = useRecoilState(atoms.modal);
  const hasDataset = useRecoilValue(selectors.hasDataset);
  const currentSamples = useRecoilValue(selectors.currentSamples);
  const clearModal = useClearModal();
  useGA();
  useSampleUpdate();
  useScreenshot();

  useEffect(() => {
    document.body.classList.toggle("noscroll", modal.visible);
  }, [modal.visible]);

  const hideModal = useMemo(() => {
    return modal.visible && !currentSamples.some((id) => id === modal.sampleId);
  }, [currentSamples]);

  useEffect(() => {
    hideModal && clearModal();
    if (!hideModal && modal.visible) {
      setModal({
        ...modal,
        sampleId: currentSamples.filter((id) => id === modal.sampleId)[0],
      });
    }
  }, [hideModal]);

  useSendMessage("set_selected_labels", { selected_labels: [] }, !hideModal);
  const ref = useRef();

  useOutsideClick(ref, clearModal);
  return (
    <>
      {modal.visible ? (
        <ModalWrapper key={0}>
          <SampleModal
            onClose={clearModal}
            ref={ref}
            sampleId={modal.sampleId}
          />
        </ModalWrapper>
      ) : null}
      <Container key={1}>
        {hasDataset && <HorizontalNav entries={PLOTS} key={"nav"} />}
        {hasDataset ? (
          <Body key={"body"}>
            <SamplesContainer key={"samples"} />
          </Body>
        ) : (
          <Loading text={"No dataset selected"} key={"loading"} />
        )}
      </Container>
    </>
  );
}

export default React.memo(Dataset);
