/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiRequestOptions } from "./ApiRequestOptions"

type Resolver<T> = (options: ApiRequestOptions) => Promise<T>
type Headers = Record<string, string>

export type OpenAPIConfig = {
  BASE: string
  VERSION: string
  WITH_CREDENTIALS: boolean
  CREDENTIALS: "omit"
  TOKEN?: string | Resolver<string> | undefined
  USERNAME?: string | Resolver<string> | undefined
  PASSWORD?: string | Resolver<string> | undefined
  HEADERS?: Headers | Resolver<Headers> | undefined
  ENCODE_PATH?: ((path: string) => string) | undefined
}

export const OpenAPI: OpenAPIConfig = {
  BASE: "",
  VERSION: "1",
  WITH_CREDENTIALS: false,
  CREDENTIALS: "omit",
  TOKEN: undefined,
  USERNAME: undefined,
  PASSWORD: undefined,
  HEADERS: {
    "Content-Security-Policy": "upgrade-insecure-requests",
  },
  ENCODE_PATH: undefined,
}
