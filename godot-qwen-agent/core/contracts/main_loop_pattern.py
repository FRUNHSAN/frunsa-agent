"""Main Loop Integration Pattern — production deployment skeleton.

This is NOT runnable code. It's the canonical integration pattern for
mounting PLAN5 into a real Agent loop. Follow this order:

  1. bp.tick()         <- ALWAYS first — decay before anything else
  2. load UserProfile  <- from disk, per user
  3. evaluate input    <- run sensors (RelationalField, etc.)
  4. check pending     <- apply accepted proposals
  5. generate response <- LLM with current contract
  6. System 2 audit    <- every 10 rounds, async, with circuit breaker
  7. save profile      <- ALWAYS last — persist after every round

Pseudo-code:

    profile = UserProfile.load(user_id)
    bp = DynamicBlueprint(defaults)
    engine = ContractEvolutionEngine()
    auditor = ContractAuditor(llm)

    while True:
        bp.tick(half_life_rounds=20)        # <-- 1. MUST BE FIRST

        user_input = get_user_input()
        ctx = evaluate(user_input, bp)

        for prop in pending_proposals:
            if engine.evaluate(prop, bp, ctx.trust):
                bp.apply_proposal(...)
                profile.record_modification(...)

        response = llm.generate(ctx.system_prompt + user_input)

        if auditor.should_audit(round_count):
            auditor.audit_async(...)

        profile.record_trust_delta(ctx.trust_delta)
        profile.save()                      # <-- 2. MUST BE LAST
        round_count += 1
"""
