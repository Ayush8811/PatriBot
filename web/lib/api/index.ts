import { API_MOCK } from "@/lib/config";
import { httpApi, type PatriBotApi } from "./http";
import { mockApi } from "./mock";

/** The API the app uses: fixtures when NEXT_PUBLIC_API_MOCK=1, otherwise HTTP via the same-origin proxy (/api/proxy). */
export const api: PatriBotApi = API_MOCK ? mockApi : httpApi;

export { ApiError, httpApi, type PatriBotApi, type RequestOptions } from "./http";
export * from "./types";
export { planRequestFromSearchParams, planRequestToSearchParams } from "./query";
