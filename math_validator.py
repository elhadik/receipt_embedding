def validate_math(data):
    """
    Validates that:
    1. The sum of all line item total prices equals the subtotal.
    2. Subtotal + tax + tip - discount equals the total.
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data:
        return False, ["No JSON data provided."]
        
    is_receipt = data.get("is_receipt", False)
    if not is_receipt:
        return False, ["Document was flagged as not a receipt: " + data.get("validation_message", "Unknown reason")]
        
    receipt_data = data.get("receipt_data")
    if not receipt_data:
        return False, ["Receipt data block is missing."]
        
    line_items = receipt_data.get("line_items") or []
    financials = receipt_data.get("financials") or {}
    
    # 1. Sum up line items total price
    calculated_subtotal = 0.0
    for idx, item in enumerate(line_items):
        qty = item.get("quantity")
        unit_p = item.get("unit_price")
        item_tot = item.get("total_price")
        
        # If total_price is missing but quantity and unit_price are there, calculate it
        if item_tot is None:
            if qty is not None and unit_p is not None:
                item_tot = float(qty) * float(unit_p)
            else:
                # Can't calculate, but let's check description
                desc = item.get("description") or f"Item {idx+1}"
                # If quantity or unit price is missing, we can't do math on this item.
                # But it's not strictly a validation error if we just skip it, unless we have no prices at all.
                continue
                
        try:
            calculated_subtotal += float(item_tot)
        except (ValueError, TypeError):
            desc = item.get("description") or f"Item {idx+1}"
            errors.append(f"Invalid total price format for item '{desc}': {item_tot}")
            
    # Compare calculated subtotal with receipt subtotal (if provided)
    receipt_subtotal = financials.get("subtotal")
    if receipt_subtotal is not None:
        try:
            receipt_subtotal_val = float(receipt_subtotal)
            if abs(calculated_subtotal - receipt_subtotal_val) > 0.01:
                errors.append(
                    f"Sum of line items ({calculated_subtotal:.2f}) does not match subtotal on receipt ({receipt_subtotal_val:.2f})"
                )
        except (ValueError, TypeError):
            errors.append(f"Invalid subtotal format on receipt: {receipt_subtotal}")
            receipt_subtotal_val = calculated_subtotal
    else:
        # If receipt subtotal is missing, use calculated subtotal
        receipt_subtotal_val = calculated_subtotal
        
    # 2. Check total financials calculation
    # subtotal + tax + tip - discount = total
    tax = financials.get("tax_amount") or 0.0
    tip = financials.get("tip_amount") or 0.0
    discount = financials.get("discount_amount") or 0.0
    total = financials.get("total")
    
    try:
        tax_val = float(tax)
    except (ValueError, TypeError):
        errors.append(f"Invalid tax format: {tax}")
        tax_val = 0.0
        
    try:
        tip_val = float(tip)
    except (ValueError, TypeError):
        errors.append(f"Invalid tip format: {tip}")
        tip_val = 0.0
        
    try:
        discount_val = float(discount)
    except (ValueError, TypeError):
        errors.append(f"Invalid discount format: {discount}")
        discount_val = 0.0
        
    expected_total = receipt_subtotal_val + tax_val + tip_val - discount_val
    
    if total is not None:
        try:
            total_val = float(total)
            if abs(expected_total - total_val) > 0.01:
                errors.append(
                    f"Calculated total ({expected_total:.2f}) does not match total on receipt ({total_val:.2f})"
                )
        except (ValueError, TypeError):
            errors.append(f"Invalid total format on receipt: {total}")
    else:
        errors.append("Total amount is missing on the receipt.")
        
    is_valid = len(errors) == 0
    return is_valid, errors
