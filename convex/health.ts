/// Health check endpoint for Python backend connectivity verification.
/// Called by ConvexBackend.health().

import { query } from "./_generated/server";

export const check = query({
  handler: async (ctx) => {
    return { status: "ok", timestamp: Date.now() };
  },
});
