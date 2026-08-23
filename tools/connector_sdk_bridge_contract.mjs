/** Read-selection and transport-shape rules for the Connector SDK bridge. */

export function includeReadForPolicy(policy) {
  if (!policy || typeof policy !== "object" || Array.isArray(policy)) {
    throw new Error("model Read policy must be an object");
  }
  if (policy.mode === "none") return () => false;
  if (policy.mode === "all") return () => true;
  throw new Error(`unsupported model Read policy: ${String(policy.mode)}`);
}

export function canonicalizeReadResponses(reads) {
  if (!Array.isArray(reads)) {
    throw new Error("Connector SDK decision-bundle Reads must be an array");
  }
  const result = [];
  const identities = new Set();
  for (const read of reads) {
    if (!read || typeof read !== "object" || Array.isArray(read)) {
      throw new Error("Connector SDK decision-bundle Read must be an object");
    }
    const readId = read.read_id;
    if (typeof readId !== "string" || readId.length === 0) {
      throw new Error("Connector SDK decision-bundle Read identity is missing");
    }
    if (identities.has(readId)) {
      throw new Error(`duplicate Connector Read identity is unsupported: ${readId}`);
    }
    identities.add(readId);
    result.push(read);
  }
  result.sort((left, right) => {
    if (left.read_id < right.read_id) return -1;
    if (left.read_id > right.read_id) return 1;
    return 0;
  });
  return result;
}
