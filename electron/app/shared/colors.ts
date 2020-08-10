import { Theme } from "@material-ui/core";

export const white100 = "hsl(0, 0%, 100%)";
export const white96 = "hsl(0, 0%, 96%)";
export const white85 = "hsl(0, 0%, 85%)";
export const white59 = "hsl(0, 0%, 59%)";
export const white20 = "hsl(0, 0%, 20%)";

export const white59a = "hsla(0, 0%, 59%, 0.5)";
export const white100a = "hsla(0, 0% , 0%, 0.14)";

export const grey81 = "hsl(216, 5%, 81%)";
export const grey66 = "hsl(220, 2%, 66%)";
export const grey46 = "hsl(208, 7%, 46%)";
export const grey23 = "hsl(207, 10%, 23%)";
export const grey10 = "hsl(216, 10%, 10%)";

export const grey46a13 = "hsla(208, 7%, 46%, 0.13)";
export const grey46a30 = "hsla(208, 7%, 46%, 0.3)";
export const grey46a70 = "hsla(208, 7%, 46%, 0.7)";

export const blue90 = "hsl(210, 20%, 90%)";
export const blue50 = "hsl(210, 20%, 50%)";
export const blue15 = "hsl(210, 20%, 15%)";

// Dark theme colors
const grey15 = "hsl(210, 11%, 15%)";
const grey19 = "hsl(214, 7%, 19%)";
const grey24 = "hsl(210, 5%, 24%)";
const grey37 = "hsl(200, 2%, 37%)";
const grey60 = "hsl(230, 3%, 60%)";
const grey68 = "hsl(220, 2%, 68%)";
const grey75 = "hsl(220, 2%, 75%)";

const orange49 = "hsl(27, 95%, 49%)";
const orange49a10 = "hsla(27, 95%, 49%, 0.1)";
const orange49a40 = "hsla(27, 95%, 49%, 0.4)";

const blue53 = "hsl(213, 100%, 53%)";

export const darkTheme = {
  background: grey19,
  backgroundDark: grey15,
  backgroundLight: grey24,
  backgroundLightBorder: grey15, // e.g. for components with the light background color
  backgroundDarkBorder: grey24,
  border: grey37,
  borderLight: grey24,
  button: grey37,
  buttonBorder: grey24,
  overlay: grey46a70,
  overlayButton: grey46a30,

  brand: orange49,
  brandTransparent: orange49a40,
  brandMoreTransparent: orange49a10,

  font: white100,
  fontDark: grey68,
  fontDarkest: grey60,

  secondary: blue53,
};

// for storybook
export const lightTheme = {
  ...darkTheme,
  background: white100,
  border: white85,
  font: white20,
};
