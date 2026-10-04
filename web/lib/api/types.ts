/**
 * Types for PatriBot API v1. Mirrors docs/api/v1.md exactly (snake_case JSON).
 * Times are ISO 8601 with offset ("+05:30"); dates are "YYYY-MM-DD"; "HH:MM" are local (IST) clock times.
 * If the contract changes, update docs/api/v1.md first, then this file.
 */

export type IsoDateTime = string;
export type IsoDate = string;
export type ClockTime = string; // "HH:MM"

export type EtaModel = "baseline_hist" | (string & {});

// GET /health
export interface HealthResponse {
  status: "ok" | (string & {});
  data_as_of: IsoDateTime;
  eta_model: EtaModel;
}

// GET /places/search
export interface ClusterPlace {
  kind: "cluster";
  id: string;
  name: string;
  stations: string[];
}
export interface StationPlace {
  kind: "station";
  id: string;
  name: string;
  cluster?: string | null;
}
export type Place = ClusterPlace | StationPlace;
export interface PlacesSearchResponse {
  results: Place[];
}

// POST /plan
export type Objective = "fastest" | "most_reliable" | "balanced";
export type HardConstraint = "overnight" | "arrive_by" | "depart_after" | "depart_before" | "classes";
export type TravelClass = "1A" | "2A" | "3A" | "3E" | "SL" | "CC" | "EC" | "EA" | "2S" | (string & {});

export interface PlanPreferences {
  overnight?: boolean;
  depart_after?: ClockTime | null;
  depart_before?: ClockTime | null;
  arrive_by?: ClockTime | null;
  classes?: TravelClass[];
  objective?: Objective;
  allow_split?: boolean;
  hard?: HardConstraint[];
}

export interface PlanRequest {
  origin: string; // cluster id or station code
  destination: string;
  date_from: IsoDate;
  date_to: IsoDate;
  preferences: PlanPreferences;
  max_results?: number;
}

export interface Leg {
  train_no: string;
  train_name: string;
  train_type: string;
  run_date: IsoDate; // departure date from the train's origin
  from_code: string;
  from_name: string;
  to_code: string;
  to_name: string;
  dep_sched: IsoDateTime;
  arr_sched: IsoDateTime;
  arr_pred_p50: IsoDateTime;
  arr_pred_p90: IsoDateTime;
  journey_min_sched: number;
  journey_min_pred_p50: number;
  reliability: number; // P(arrival delay <= 30 min), 0..1
  history_runs: number; // 0 = fallback estimate
  overnight: boolean;
  classes: TravelClass[];
}

export interface ScoreBreakdown {
  journey_time: number;
  reliability: number;
  preference: number;
  transfer: number;
  [component: string]: number;
}

export type ItineraryKind = "direct" | "split";
export type SplitKind = "split_itinerary" | "break_journey";

export interface Itinerary {
  id: string;
  kind: ItineraryKind;
  score: number; // 0..1, higher is better
  score_breakdown: ScoreBreakdown;
  why: string[];
  legs: Leg[];
  layover_min_sched: number | null;
  layover_min_p90: number | null; // can be negative = risky
  split_kind: SplitKind | null;
  warnings: string[];
  irctc_url: string;
}

export interface PlanMeta {
  eta_model: EtaModel;
  data_as_of: IsoDateTime;
  dates_searched: number;
  candidates_considered: number;
  bookable_from: IsoDate;
  bookable_to: IsoDate;
}

export interface PlanResponse {
  /** The normalised request; origin/destination resolved to station lists. Shape is not pinned by the contract. */
  query: Record<string, unknown>;
  itineraries: Itinerary[];
  meta: PlanMeta;
}

// GET /trains/{train_no}
export interface RouteStop {
  seq: number;
  code: string;
  name: string;
  arr: ClockTime | null;
  dep: ClockTime | null;
  day: number;
  distance_km: number;
  delay_p50_min: number | null;
  delay_p90_min: number | null;
  history_runs: number;
}

export type Weekday = "MON" | "TUE" | "WED" | "THU" | "FRI" | "SAT" | "SUN";

export interface TrainResponse {
  train_no: string;
  train_name: string;
  train_type: string;
  origin: string;
  destination: string;
  running_days: Weekday[];
  classes: TravelClass[];
  corridors: string[];
  route: RouteStop[];
}

// GET /trains/{train_no}/performance
export interface MonthlyPerformance {
  month: string; // "YYYY-MM"
  runs: number;
  final_delay_p50: number;
  final_delay_p90: number;
  pct_within_30min: number;
}
export interface RecentRun {
  run_date: IsoDate;
  final_delay_min: number | null;
  run_state: "complete" | (string & {});
}
export interface PerformanceResponse {
  train_no: string;
  runs: number;
  on_time_pct: number;
  by_month: MonthlyPerformance[];
  recent_runs: RecentRun[];
}

// POST /chat (SSE)
export interface ChatRequest {
  session_id: string;
  message: string;
}
export type ChatEvent =
  | { event: "token"; data: { text: string } }
  | { event: "itineraries"; data: Itinerary[] }
  | { event: "done"; data: { usage: { queries_left_today: number } } }
  | { event: "error"; data: { detail: string } };

// Errors
export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}
export interface ErrorBody {
  detail: string | ValidationErrorItem[];
}
