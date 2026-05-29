#!/bin/bash
find ~/nazokake-evaluator/frontend ~/nazokake-evaluator/backend ~/nazokake-evaluator/pages ~/nazokake-evaluator/service_api ~/nazokake-evaluator/app.py ~/nazokake-evaluator/main.py -type f \( -name "*.py" -o -name "*.html" -o -name "*.js" -o -name "*.css" \) 2>/dev/null | while read file; do
    echo "=========================================="
    echo "?? File: $file"
    echo "=========================================="
    cat "$file"
    echo ""
done
