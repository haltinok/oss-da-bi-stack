// The names a report shows for fields whose cube has a role ("Ship month name" for ship_dates.month_name): set once from what the page loaded (the compiled spec's `members`, or the
// catalog the designer reads), and read wherever a default label is made from a member. Most fields have none and get their name from the member itself.
const labels = new Map();

/** Remembers { "cube.member": "Label" } (what the model's `label_prefix` made of them); entries are added to what is there. */
export function setMemberLabels(map) {
  for (const [member, label] of Object.entries(map || {})) labels.set(member, label);
}

/** The label a role-playing cube gives a field, capitalised, or undefined when there is none. */
export const memberLabel = (member) => {
  const l = labels.get(member);
  return l ? l.charAt(0).toUpperCase() + l.slice(1) : undefined;
};
