/// Schema for AIOS data models in Convex.
/// Deploy this file to your Convex project to define the document types.

import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  organizations: defineTable({
    name: v.string(),
    slug: v.string(),
    is_active: v.boolean(),
    extra_data: v.optional(v.any()),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_slug", ["slug"]),

  users: defineTable({
    email: v.string(),
    hashed_password: v.string(),
    api_key_hash: v.optional(v.string()),
    org_id: v.string(),
    role: v.string(),
    email_verified: v.optional(v.boolean()),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_email", ["email"])
    .index("by_org", ["org_id"]),

  agents: defineTable({
    name: v.string(),
    agent_type: v.string(),
    org_id: v.string(),
    llm_config: v.any(),
    system_prompt: v.string(),
    tools: v.array(v.string()),
    memory_config: v.any(),
    governance_config: v.optional(v.any()),
    status: v.string(),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_org", ["org_id"]),

  teams: defineTable({
    name: v.string(),
    org_id: v.string(),
    routing_strategy: v.string(),
    orchestrator_agent_id: v.optional(v.string()),
    manager_agent_id: v.optional(v.string()),
    extra_data: v.optional(v.any()),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_org", ["org_id"]),

  conversations: defineTable({
    org_id: v.string(),
    channel_connection_id: v.optional(v.string()),
    team_id: v.optional(v.string()),
    agent_id: v.optional(v.string()),
    channel: v.string(),
    external_id: v.optional(v.string()),
    extra_data: v.optional(v.any()),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_org", ["org_id"])
    .index("by_external", ["external_id"]),

  messages: defineTable({
    conversation_id: v.string(),
    org_id: v.string(),
    role: v.string(),
    content: v.string(),
    agent_id: v.optional(v.string()),
    tool_calls: v.optional(v.any()),
    tool_results: v.optional(v.any()),
    channel_message_id: v.optional(v.string()),
    extra_data: v.optional(v.any()),
    created_at: v.optional(v.string()),
  }).index("by_conversation", ["conversation_id"])
    .index("by_org", ["org_id"]),

  channel_connections: defineTable({
    org_id: v.string(),
    channel_type: v.string(),
    label: v.string(),
    config: v.any(),
    is_active: v.boolean(),
    agent_id: v.optional(v.string()),
    team_id: v.optional(v.string()),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_org", ["org_id"]),

  artifacts: defineTable({
    org_id: v.string(),
    conversation_id: v.optional(v.string()),
    agent_id: v.optional(v.string()),
    filename: v.string(),
    content_type: v.string(),
    size_bytes: v.number(),
    storage_path: v.string(),
    description: v.string(),
    created_at: v.optional(v.string()),
  }).index("by_org", ["org_id"])
    .index("by_conversation", ["conversation_id"]),

  tools: defineTable({
    name: v.string(),
    description: v.string(),
    org_id: v.string(),
    input_schema: v.any(),
    output_schema: v.any(),
    code_reference: v.string(),
    is_builtin: v.boolean(),
    status: v.string(),
    created_at: v.optional(v.string()),
  }).index("by_name", ["name"])
    .index("by_org", ["org_id"]),

  memories: defineTable({
    agent_id: v.string(),
    org_id: v.string(),
    type: v.string(),
    content: v.string(),
    extra_data: v.optional(v.any()),
    created_at: v.optional(v.string()),
  }).index("by_agent", ["agent_id"])
    .index("by_org", ["org_id"]),

  agent_instances: defineTable({
    agent_id: v.string(),
    org_id: v.string(),
    status: v.string(),
    extra_data: v.optional(v.any()),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_agent", ["agent_id"])
    .index("by_org", ["org_id"]),

  usage_records: defineTable({
    org_id: v.string(),
    date: v.string(),
    messages: v.number(),
    llm_tokens: v.number(),
    llm_calls: v.number(),
  }).index("by_org_date", ["org_id", "date"]),

  remote_instances: defineTable({
    org_id: v.string(),
    name: v.string(),
    base_url: v.string(),
    api_key: v.string(),
    client_org_id: v.string(),
    is_active: v.boolean(),
    extra_data: v.optional(v.any()),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_org", ["org_id"]),

  invitations: defineTable({
    org_id: v.string(),
    email: v.string(),
    role: v.string(),
    token: v.string(),
    accepted: v.boolean(),
    expires_at: v.optional(v.string()),
    created_at: v.optional(v.string()),
  }).index("by_token", ["token"])
    .index("by_org", ["org_id"]),

  audit_logs: defineTable({
    org_id: v.string(),
    user_id: v.optional(v.string()),
    action: v.string(),
    resource_type: v.string(),
    resource_id: v.optional(v.string()),
    details: v.optional(v.any()),
    ip_address: v.optional(v.string()),
    created_at: v.optional(v.string()),
  }).index("by_org", ["org_id"])
    .index("by_action", ["action"]),

  oauth_accounts: defineTable({
    user_id: v.string(),
    provider: v.string(),
    provider_user_id: v.string(),
    extra_data: v.optional(v.any()),
    created_at: v.optional(v.string()),
    updated_at: v.optional(v.string()),
  }).index("by_user", ["user_id"])
    .index("by_provider", ["provider", "provider_user_id"]),
});
