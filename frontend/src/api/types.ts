export interface MealItem {
  food_name: string;
  qty_g: number;
  confidence: number; // 0-1 USDA match confidence from the backend
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  fdc_id: number;
  /** Alternative USDA description strings, first entry = current match */
  candidates: string[];
  /** "USDA" for real FoodData Central matches, "LLM_ESTIMATE" otherwise */
  source: string;
  /** True when nutrition was estimated by the LLM (no confident USDA match) */
  estimated: boolean;
  /** Composite dish this ingredient was auto-decomposed from; null if atomic */
  source_dish?: string | null;
  /** True for a prepared/multi-ingredient dish that can be broken into ingredients */
  is_composite?: boolean;
  /** null = FDC reports no value (unknown, not zero) */
  sugar_g?: number | null;
  sat_fat_g?: number | null;
  /**
   * Promoted macros FDC has no value for. Their numeric field is sent as 0 for
   * older clients; treat them as unknown, not zero.
   */
  unknown_nutrients?: string[];
  /** Full USDA nutrient breakdown (kept so saving a meal preserves micros) */
  nutrients?: Record<string, { amount: number; unit: string }>;
  /** Edited weight when saving; macros refer to qty_g. Defaults to qty_g. */
  target_qty_g?: number;
}

export interface MyMealSummary {
  id: string;
  name: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  n_ingredients: number;
}

export interface MyMealDetail extends MyMealSummary {
  ingredients: MealItem[];
  /** ISO-8601 with microseconds; echo back as expected_updated_at on PUT */
  updated_at: string;
}

export interface SaveMealRequest {
  name: string;
  portion?: number;
  ingredients: MealItem[];
}

export interface UpdateMealRequest {
  name: string;
  /** The detail's updated_at, for optimistic concurrency */
  expected_updated_at: string;
  ingredients: MealItem[];
}

export interface IngredientOverride {
  index: number;
  qty_g: number;
}

export interface LogMyMealRequest {
  meal_type: MealCategory;
  portion?: number;
  ingredients?: IngredientOverride[];
}

export interface LogMyMealResponse {
  meal_id: string;
  meal_type: string;
  n_items: number;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  message: string;
}

/** A confirmation-card item plus its user-edited gram weight, for direct logging. */
export interface LogItemInput extends MealItem {
  /** User-edited grams (before the portion multiplier); qty_g stays the base. */
  target_qty_g: number;
}

export interface LogItemsRequest {
  meal_type: MealCategory;
  portion: number;
  items: LogItemInput[];
}

export type MealCategory = 'breakfast' | 'brunch' | 'lunch' | 'dinner' | 'snack';

export const MEAL_CATEGORIES: MealCategory[] = [
  'breakfast',
  'brunch',
  'lunch',
  'dinner',
  'snack',
];

export interface LogMealRequest {
  user_input: string;
  conversation_id?: string | null;
  image_b64?: string | null;
  meal_type?: MealCategory | null;
  action?: string | null;
}

export interface LogMealResponse {
  status: string;
  message: string;
  paused: boolean;
  items: MealItem[];
  meal_id?: string | null;
  /** Set on coaching replies once persisted; absent for meal logging. */
  response_id?: string | null;
}

export interface CategoryStat {
  meal_type: MealCategory;
  n_meals: number;
  days_logged: number;
  avg_kcal: number;
  avg_protein_g: number;
  avg_carbs_g: number;
  avg_fat_g: number;
  avg_fiber_g: number;
  total_kcal: number;
  share_kcal_pct: number;
}

export interface MealTypeEntry {
  meal_type: string; // 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'brunch'
  kcal: number;
  summary: string; // e.g. "Scrambled eggs, Sourdough toast, Flat white"
}

export interface TodayTotals {
  kcal: number;
  protein_g: number;
  fiber_g: number;
  n_meals: number;
  by_type?: MealTypeEntry[];
}

export type TrackingMode = 'goals' | 'mindful';

export interface GoalData {
  tracking_mode?: TrackingMode;
  kcal_goal: number | null;
  protein_goal: number | null;
  fiber_goal: number | null;
  dietary_prefs: Record<string, unknown>;
  /** Declared health conditions; picks which dietary guidelines the coach may cite. */
  conditions?: string[];
  /** Typical first-meal time as "HH:MM" (24h), captured during onboarding. */
  first_meal_time?: string | null;
  streak_days?: number;
}

export interface MindfulNutrient {
  name: string;
  amount: number;
  unit: string;
}

export interface MindfulAlert {
  nutrient: string;
  amount: number;
  limit: number;
  unit: string;
  source: string;
  url: string;
}

export interface MindfulDay {
  tracking_mode: string;
  date: string;
  nutrients: MindfulNutrient[];
  alerts: MindfulAlert[];
}

export interface TelegramLinkCode {
  code: string;
  expires_in: number;
  bot_username: string;
}

export interface TelegramLinkStatus {
  linked: boolean;
}

export interface DayTrend {
  date: string; // ISO date
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fiber_g: number;
  n_meals: number;
  junk_meals: number;
}

export interface NutrientCheckupItem {
  name: string;
  avg: number;
  prev_avg: number;
  unit: string;
  trend_pct: number | null;
  direction: 'up' | 'down' | 'flat';
  rda_pct: number | null;
}

export interface NutrientCheckupResponse {
  date: string; // ISO date
  nutrients: NutrientCheckupItem[];
  generated_at: string;
  notable: string[];
  summary_text: string | null;
}

export interface PendingNudgeResponse {
  summary_text: string | null;
}

export interface QuotaStatus {
  used: number
  limit: number
  remaining: number
  exhausted: boolean
  tier: 'free' | 'paid'
}

export interface UpgradeResponse {
  upgraded: boolean
  new_quota: number
}
