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
}

export interface LogMealRequest {
  user_input: string;
  conversation_id?: string | null;
  image_b64?: string | null;
}

export interface LogMealResponse {
  status: string;
  message: string;
  paused: boolean;
  items: MealItem[];
}

export interface TodayTotals {
  kcal: number;
  protein_g: number;
  fiber_g: number;
  n_meals: number;
}

export interface GoalData {
  kcal_goal: number;
  protein_goal: number;
  fiber_goal: number;
  dietary_prefs: Record<string, unknown>;
  streak_days?: number;
}

export interface DayTrend {
  date: string; // ISO date
  kcal: number;
  protein_g: number;
  fiber_g: number;
  n_meals: number;
  junk_meals: number;
}
