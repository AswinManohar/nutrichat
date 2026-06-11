export type ActivityLevel = 'sedentary' | 'lightly_active' | 'moderately_active' | 'very_active' | 'extra_active';
export type BiologicalSex = 'male' | 'female';
export type DietGoal = 'lose' | 'maintain' | 'gain';

export interface OnboardingInputs {
  weightKg: number;
  heightCm: number;
  ageYears: number;
  sex: BiologicalSex;
  activityLevel: ActivityLevel;
  dietGoal: DietGoal;
}

export interface CalculatedTargets {
  bmr: number;
  tdee: number;
  kcalGoal: number;
  proteinGoal: number;
  fiberGoal: number;
}

const ACTIVITY_MULTIPLIERS: Record<ActivityLevel, number> = {
  sedentary: 1.2,
  lightly_active: 1.375,
  moderately_active: 1.55,
  very_active: 1.725,
  extra_active: 1.9,
};

export const calculateTDEE = (inputs: OnboardingInputs): CalculatedTargets => {
  const { weightKg, heightCm, ageYears, sex, activityLevel, dietGoal } = inputs;

  // Mifflin-St Jeor Equation
  const bmr =
    sex === 'male'
      ? 10 * weightKg + 6.25 * heightCm - 5 * ageYears + 5
      : 10 * weightKg + 6.25 * heightCm - 5 * ageYears - 161;

  const multiplier = ACTIVITY_MULTIPLIERS[activityLevel] || 1.2;
  const tdee = bmr * multiplier;

  // Calorie targets based on goal
  let kcalGoal = tdee;
  if (dietGoal === 'lose') {
    kcalGoal = Math.max(1200, tdee - 500); // 1200 kcal is generally the safe minimum
  } else if (dietGoal === 'gain') {
    kcalGoal = tdee + 500;
  }

  // Protein targets: 2.0g per kg of bodyweight as a robust default for active/tracking individuals, or ~25% of energy
  const proteinGoal = Math.max(60, weightKg * 1.8);

  // Fiber targets: 14g per 1000 kcal, or 25-38g minimums
  const baseFiber = (kcalGoal / 1000) * 14;
  const genderMinFiber = sex === 'male' ? 38 : 25;
  const fiberGoal = Math.max(genderMinFiber, baseFiber);

  return {
    bmr: Math.round(bmr),
    tdee: Math.round(tdee),
    kcalGoal: Math.round(kcalGoal),
    proteinGoal: Math.round(proteinGoal),
    fiberGoal: Math.round(fiberGoal),
  };
}
