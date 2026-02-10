# Fast deployment config for JARS Agent
# Optimized for speed while maintaining accuracy

cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\agent

agentcore deploy --auto-update-on-conflict `
  --env AWS_REGION=us-east-1 `
  --env BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 `
  --env BEDROCK_GUARDRAIL_ID=arn:aws:bedrock:us-east-1:021862553142:guardrail-profile/us.guardrail.v1:0 `
  --env BEDROCK_GUARDRAIL_VERSION=DRAFT `
  --env BEDROCK_KB_ID=G6GLWTUKEL `
  --env BEDROCK_KB_DATASOURCE_ID=WTYVWINQP9 `
  --env AGENTCORE_GATEWAY_ENDPOINT=https://jars-gw-afejhtqoqd.gateway.bedrock-agentcore.us-east-1.amazonaws.com `
  --env BACKEND_API_BASE=https://backend-placeholder.example.com `
  --env USE_LOCAL_MOCKS=false `
  --env ROUTER_MODE=semantic_enforce `
  --env ROUTER_POLICY_VERSION=v1 `
  --env ROUTER_INTENT_CONF_MIN=0.70 `
  --env ROUTER_TOP2_GAP_MIN=0.15 `
  --env ROUTER_SCENARIO_CONF_MIN=0.75 `
  --env ROUTER_MAX_CLARIFY_QUESTIONS=2 `
  --env RESPONSE_MODE=llm_enforce `
  --env RESPONSE_PROMPT_VERSION=answer_synth_v2 `
  --env RESPONSE_SCHEMA_VERSION=answer_plan_v2 `
  --env RESPONSE_POLICY_VERSION=advice_policy_v1 `
  --env RESPONSE_MAX_RETRIES=1 `
  --env ENCODING_GATE_ENABLED=false `
  --env ENCODING_REPAIR_ENABLED=true `
  --env ENCODING_REPAIR_SCORE_MIN=0.12 `
  --env ENCODING_FAILFAST_SCORE_MIN=0.45 `
  --env ENCODING_REPAIR_MIN_DELTA=0.10 `
  --env ENCODING_NORMALIZATION_FORM=NFC `
  --env LOG_LEVEL=info
