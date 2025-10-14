#!/bin/bash

# Test script for team statistics test run metrics API
# This script tests the modified API endpoint to ensure it returns the correct structure

API_URL="http://localhost:9999/api/admin/team_statistics/test_run_metrics?days=7"

echo "Testing Team Statistics Test Run Metrics API"
echo "=============================================="
echo ""
echo "Endpoint: $API_URL"
echo ""

# Make API call and save response
RESPONSE=$(curl -s "$API_URL" -H "Authorization: Bearer YOUR_TOKEN_HERE")

# Check if response is valid JSON
if ! echo "$RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
    echo "❌ Response is not valid JSON"
    echo "$RESPONSE"
    exit 1
fi

echo "✓ Response is valid JSON"
echo ""

# Check for required fields
echo "Checking required fields..."

# Check dates
if echo "$RESPONSE" | grep -q '"dates"'; then
    echo "✓ 'dates' field exists"
else
    echo "❌ 'dates' field missing"
    exit 1
fi

# Check per_team_daily
if echo "$RESPONSE" | grep -q '"per_team_daily"'; then
    echo "✓ 'per_team_daily' field exists"
else
    echo "❌ 'per_team_daily' field missing"
    exit 1
fi

# Check per_team_pass_rate
if echo "$RESPONSE" | grep -q '"per_team_pass_rate"'; then
    echo "✓ 'per_team_pass_rate' field exists"
else
    echo "❌ 'per_team_pass_rate' field missing"
    exit 1
fi

# Check by_status
if echo "$RESPONSE" | grep -q '"by_status"'; then
    echo "✓ 'by_status' field exists"
else
    echo "❌ 'by_status' field missing"
    exit 1
fi

# Check by_team
if echo "$RESPONSE" | grep -q '"by_team"'; then
    echo "✓ 'by_team' field exists"
else
    echo "❌ 'by_team' field missing"
    exit 1
fi

# Check overall
if echo "$RESPONSE" | grep -q '"overall"'; then
    echo "✓ 'overall' field exists"
else
    echo "❌ 'overall' field missing"
    exit 1
fi

echo ""
echo "✓ All required fields are present!"
echo ""
echo "Response structure (first 500 chars):"
echo "$RESPONSE" | python3 -m json.tool | head -30

