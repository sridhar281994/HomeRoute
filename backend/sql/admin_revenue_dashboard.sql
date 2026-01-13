-- Basic admin revenue dashboard (this repo's schema, integer IDs)
-- Revenue is derived from subscription_plans.price_inr * count(user_subscriptions)

SELECT
  sp.id         AS plan_id,
  sp.name       AS plan_name,
  sp.price_inr  AS price_inr,
  COUNT(us.id)  AS subscriptions,
  (sp.price_inr * COUNT(us.id)) AS revenue_inr
FROM subscription_plans sp
LEFT JOIN user_subscriptions us
  ON us.plan_id = sp.id
GROUP BY sp.id, sp.name, sp.price_inr
ORDER BY revenue_inr DESC;

