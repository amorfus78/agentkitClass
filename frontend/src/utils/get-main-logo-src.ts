import { Theme } from "~/styles/themes"

import { CONSTANTS  } from "./constants"

export const getMainLogoSrc = (theme?: string) => {
  if (theme === Theme.Dark) {
    return CONSTANTS.LOGO_FULL_DARK_SRC
  }

  return CONSTANTS.LOGO_FULL_SRC
}
