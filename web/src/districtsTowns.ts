// Single source of truth for District → State → Area.
//
// Replace the contents of `DISTRICTS_TOWNS` with your real dataset.
// Expected structure:
// {
//   "District1": {
//     "State1": ["Area1", "Area2"]
//   }
// }
export type DistrictsTowns = Record<string, Record<string, string[]>>;

export const DISTRICTS_TOWNS: DistrictsTowns = {};

export default DISTRICTS_TOWNS;

