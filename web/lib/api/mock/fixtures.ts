/**
 * Demo fixtures for NEXT_PUBLIC_API_MOCK=1. Timetables are illustrative approximations of real Kolkata → Delhi
 * corridor trains (not authoritative IR data); delay percentiles are synthetic. Only Kolkata → Delhi has trains.
 */
import type { ClusterPlace, StationPlace, TravelClass, Weekday } from "../types";

export const STATIONS: Record<string, string> = {
  // Kolkata cluster
  HWH: "Howrah Jn",
  SDAH: "Sealdah",
  KOAA: "Kolkata (Chitpur)",
  SRC: "Santragachi Jn",
  SHM: "Shalimar",
  // Delhi cluster
  NDLS: "New Delhi",
  DLI: "Old Delhi Jn",
  NZM: "Hazrat Nizamuddin",
  ANVT: "Anand Vihar Terminal",
  DEE: "Delhi Sarai Rohilla",
  // Patna cluster
  PNBE: "Patna Jn",
  RJPB: "Rajendra Nagar Terminal",
  PPTA: "Patliputra Jn",
  DNR: "Danapur",
  // Mumbai cluster
  CSMT: "Chhatrapati Shivaji Maharaj Terminus",
  MMCT: "Mumbai Central",
  BDTS: "Bandra Terminus",
  LTT: "Lokmanya Tilak Terminus",
  DR: "Dadar",
  // Bengaluru cluster
  SBC: "KSR Bengaluru",
  YPR: "Yesvantpur Jn",
  SMVB: "SMVT Bengaluru",
  // Hyderabad cluster
  SC: "Secunderabad Jn",
  HYB: "Hyderabad Deccan",
  KCG: "Kacheguda",
  // Chennai cluster
  MAS: "MGR Chennai Central",
  MS: "Chennai Egmore",
  TBM: "Tambaram",
  // Corridor stations
  BWN: "Barddhaman Jn",
  ASN: "Asansol Jn",
  DHN: "Dhanbad Jn",
  GAYA: "Gaya Jn",
  DDU: "Pt. Deen Dayal Upadhyaya Jn",
  PRYJ: "Prayagraj Jn",
  CNB: "Kanpur Central",
  JSME: "Jasidih Jn",
  KIUL: "Kiul Jn",
  ARA: "Ara Jn",
  BXR: "Buxar",
  PURI: "Puri",
  BBS: "Bhubaneswar",
  CTC: "Cuttack",
  TATA: "Tatanagar Jn",
  BKSC: "Bokaro Steel City",
};

export const CLUSTERS: Record<string, { name: string; stations: string[]; aliases: string[] }> = {
  KOLKATA: { name: "Kolkata", stations: ["HWH", "SDAH", "KOAA", "SRC", "SHM"], aliases: ["calcutta", "howrah"] },
  DELHI: { name: "Delhi", stations: ["NDLS", "DLI", "NZM", "ANVT", "DEE"], aliases: ["new delhi", "dilli"] },
  PATNA: { name: "Patna", stations: ["PNBE", "RJPB", "PPTA", "DNR"], aliases: [] },
  MUMBAI: { name: "Mumbai", stations: ["CSMT", "MMCT", "BDTS", "LTT", "DR"], aliases: ["bombay"] },
  BENGALURU: { name: "Bengaluru", stations: ["SBC", "YPR", "SMVB"], aliases: ["bangalore"] },
  HYDERABAD: { name: "Hyderabad", stations: ["SC", "HYB", "KCG"], aliases: ["secunderabad"] },
  CHENNAI: { name: "Chennai", stations: ["MAS", "MS", "TBM"], aliases: ["madras"] },
};

export function clusterOf(code: string): string | null {
  for (const [id, c] of Object.entries(CLUSTERS)) if (c.stations.includes(code)) return id;
  return null;
}

export function clusterPlace(id: string): ClusterPlace {
  const c = CLUSTERS[id]!;
  return { kind: "cluster", id, name: `${c.name} (all stations)`, stations: c.stations };
}

export function stationPlace(code: string): StationPlace {
  return { kind: "station", id: code, name: STATIONS[code] ?? code, cluster: clusterOf(code) };
}

export interface FixtureStop {
  code: string;
  arr: string | null;
  dep: string | null;
  day: number;
  km: number;
  p50: number; // arrival delay percentiles (min)
  p90: number;
}

export interface FixtureTrain {
  train_no: string;
  train_name: string;
  train_type: string;
  running_days: Weekday[];
  classes: TravelClass[];
  corridors: string[];
  reliability: number; // P(final delay <= 30 min)
  history_runs: number;
  stops: FixtureStop[];
}

const ALL_DAYS: Weekday[] = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];

const s = (code: string, arr: string | null, dep: string | null, day: number, km: number, p50: number, p90: number) => ({
  code,
  arr,
  dep,
  day,
  km,
  p50,
  p90,
});

export const TRAINS: Record<string, FixtureTrain> = {
  "12301": {
    train_no: "12301",
    train_name: "Howrah Rajdhani Express",
    train_type: "Rajdhani",
    running_days: ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
    classes: ["1A", "2A", "3A"],
    corridors: ["KOL-DEL"],
    reliability: 0.74,
    history_runs: 41,
    stops: [
      s("HWH", null, "16:50", 1, 0, 0, 5),
      s("BWN", "17:51", "17:53", 1, 95, 3, 10),
      s("ASN", "18:52", "18:54", 1, 200, 6, 18),
      s("DHN", "19:50", "19:55", 1, 259, 10, 26),
      s("GAYA", "22:02", "22:05", 1, 458, 14, 38),
      s("DDU", "00:30", "00:40", 2, 661, 20, 50),
      s("PRYJ", "02:28", "02:30", 2, 813, 24, 58),
      s("CNB", "04:35", "04:40", 2, 1007, 28, 66),
      s("NDLS", "10:05", null, 2, 1451, 33, 75),
    ],
  },
  "12313": {
    train_no: "12313",
    train_name: "Sealdah Rajdhani Express",
    train_type: "Rajdhani",
    running_days: ALL_DAYS,
    classes: ["1A", "2A", "3A"],
    corridors: ["KOL-DEL"],
    reliability: 0.84,
    history_runs: 38,
    stops: [
      s("SDAH", null, "16:30", 1, 0, 0, 4),
      s("ASN", "18:41", "18:43", 1, 196, 4, 12),
      s("DHN", "19:43", "19:48", 1, 255, 6, 17),
      s("GAYA", "21:59", "22:02", 1, 454, 9, 25),
      s("DDU", "00:25", "00:35", 2, 657, 12, 32),
      s("PRYJ", "02:15", "02:17", 2, 809, 13, 35),
      s("CNB", "04:28", "04:33", 2, 1003, 15, 38),
      s("NDLS", "10:00", null, 2, 1447, 18, 44),
    ],
  },
  "12273": {
    train_no: "12273",
    train_name: "Howrah New Delhi Duronto Express",
    train_type: "Duronto",
    running_days: ["THU", "SAT"],
    classes: ["1A", "2A", "3A", "SL"],
    corridors: ["KOL-DEL"],
    reliability: 0.62,
    history_runs: 0,
    stops: [
      s("HWH", null, "08:35", 1, 0, 0, 10),
      s("ASN", "10:52", "10:57", 1, 200, 8, 25),
      s("DHN", "12:05", "12:10", 1, 259, 12, 32),
      s("DDU", "18:20", "18:30", 1, 661, 20, 55),
      s("CNB", "23:25", "23:33", 1, 1007, 25, 70),
      s("NDLS", "05:00", null, 2, 1451, 30, 85),
    ],
  },
  "12381": {
    train_no: "12381",
    train_name: "Poorva Express",
    train_type: "Superfast",
    running_days: ["WED", "THU", "SUN"],
    classes: ["2A", "3A", "SL"],
    corridors: ["KOL-DEL"],
    reliability: 0.38,
    history_runs: 29,
    stops: [
      s("HWH", null, "08:15", 1, 0, 0, 8),
      s("BWN", "09:26", "09:28", 1, 95, 6, 20),
      s("ASN", "10:33", "10:35", 1, 200, 14, 40),
      s("DHN", "11:43", "11:48", 1, 259, 20, 55),
      s("GAYA", "14:12", "14:17", 1, 458, 35, 95),
      s("DDU", "18:10", "18:25", 1, 661, 55, 150),
      s("PRYJ", "20:20", "20:25", 1, 813, 58, 158),
      s("CNB", "23:05", "23:12", 1, 1007, 62, 165),
      s("NDLS", "06:25", null, 2, 1451, 65, 172),
    ],
  },
  "22347": {
    train_no: "22347",
    train_name: "Howrah Patna Vande Bharat Express",
    train_type: "Vande Bharat",
    running_days: ["MON", "WED", "THU", "FRI", "SAT", "SUN"],
    classes: ["EC", "CC"],
    corridors: ["KOL-DEL"],
    reliability: 0.79,
    history_runs: 35,
    stops: [
      s("HWH", null, "05:55", 1, 0, 0, 4),
      s("BWN", "06:55", "06:57", 1, 95, 2, 9),
      s("ASN", "07:56", "07:58", 1, 200, 4, 14),
      s("JSME", "09:10", "09:12", 1, 312, 6, 20),
      s("KIUL", "10:40", "10:42", 1, 432, 9, 28),
      s("PNBE", "13:35", null, 1, 532, 12, 40),
    ],
  },
  "12309": {
    train_no: "12309",
    train_name: "Rajendra Nagar Patna Rajdhani Express",
    train_type: "Rajdhani",
    running_days: ALL_DAYS,
    classes: ["1A", "2A", "3A"],
    corridors: ["DEL-PAT", "KOL-DEL"],
    reliability: 0.81,
    history_runs: 40,
    stops: [
      s("RJPB", null, "19:00", 1, 0, 0, 3),
      s("PNBE", "19:13", "19:25", 1, 6, 2, 8),
      s("ARA", "20:05", "20:07", 1, 54, 5, 14),
      s("BXR", "20:55", "20:57", 1, 123, 7, 18),
      s("DDU", "22:50", "23:00", 1, 214, 11, 30),
      s("PRYJ", "01:05", "01:07", 2, 366, 14, 36),
      s("CNB", "03:20", "03:25", 2, 560, 17, 44),
      s("NDLS", "07:40", null, 2, 1001, 22, 55),
    ],
  },
  "12801": {
    train_no: "12801",
    train_name: "Purushottam Express",
    train_type: "Superfast",
    running_days: ALL_DAYS,
    classes: ["2A", "3A", "SL"],
    corridors: ["KOL-DEL"],
    reliability: 0.52,
    history_runs: 33,
    stops: [
      s("PURI", null, "21:45", 1, 0, 0, 6),
      s("BBS", "23:20", "23:25", 1, 63, 5, 15),
      s("CTC", "00:05", "00:10", 2, 91, 8, 22),
      s("TATA", "07:05", "07:15", 2, 449, 18, 55),
      s("BKSC", "10:00", "10:05", 2, 603, 25, 70),
      s("GAYA", "15:30", "15:35", 2, 873, 32, 85),
      s("DDU", "19:40", "19:50", 2, 1076, 38, 95),
      s("PRYJ", "22:10", "22:15", 2, 1228, 42, 105),
      s("CNB", "01:10", "01:18", 3, 1422, 45, 110),
      s("NDLS", "07:25", null, 3, 1866, 50, 120),
    ],
  },
};

/** Curated 2-leg split candidates (architecture §7.2 hub list, fixtures only). */
export const SPLITS: { leg1: string; hub: string; leg2: string }[] = [
  { leg1: "22347", hub: "PNBE", leg2: "12309" },
  { leg1: "12381", hub: "DDU", leg2: "12801" },
];

export const IRCTC_URL = "https://www.irctc.co.in/nget/train-search";
