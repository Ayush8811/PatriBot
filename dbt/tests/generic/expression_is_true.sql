{# Fails for rows where the boolean expression is not true. #}
{% test expression_is_true(model, expression, column_name=none) %}
select *
from {{ model }}
where not coalesce(({{ expression }}), false)
{% endtest %}
