# Salesforce Duplicate Management Setup Guide

**Audience:** Salesforce Administrator
**Goal:** Configure native Salesforce Duplicate Management so that sales reps are warned when they create a Lead that already exists as a Contact.

This guide walks through Salesforce Setup step by step. No developer skills are required. All of the configuration described here is done through clicks in the Salesforce user interface.

---

## Why do this?

ADAM's Duplicate Lead Detection module finds _existing_ duplicates in your org. This guide configures Salesforce to _prevent new ones_ by showing a warning to reps at the moment they save a Lead that matches an existing Contact.

The two work together:
- **ADAM** → retrospective audit: finds duplicates already in the org.
- **Duplicate Management** → prospective guard: warns reps before new duplicates are created.

---

## Section 1 — Create a Custom Matching Rule

A Matching Rule tells Salesforce how to compare two records to decide whether they are duplicates. You will create one rule that compares a Lead against existing Contacts on three fields.

### Steps

1. Go to **Setup** (gear icon, top right) → in the Quick Find box type **Matching Rules** → click **Matching Rules**.

2. Click **New Rule**.

3. In the **Object** dropdown, select **Lead**.

4. Fill in the rule details:
   - **Rule Name:** `Lead Matches Existing Contact`
   - **Description:** `Flags a Lead as a potential duplicate when First Name, Last Name, and Company all match a Contact's First Name, Last Name, and Account Name.`

5. Under **Matching Criteria**, add three rows. Click **Add Row** between each:

   | Lead Field | Matching Method | Contact Field |
   |---|---|---|
   | First Name | **Exact** | First Name |
   | Last Name | **Exact** | Last Name |
   | Company | **Exact** | Account Name |

   > **Important:** Select **Exact** (not Fuzzy or Edit Distance) for every row. This matches ADAM's logic and avoids false positives from similar-but-different names.

6. Click **Save**.

7. The rule is saved in **Inactive** status. To activate it:
   - Find the rule in the list.
   - Click the dropdown arrow next to the rule name → click **Activate**.
   - Confirm the activation prompt.

The rule is now active. On its own it does nothing visible — you need a Duplicate Rule (Section 2) to attach a user-facing action to it.

---

## Section 2 — Create a Duplicate Rule

A Duplicate Rule uses a Matching Rule to decide what happens when a match is found. You will create one rule that warns reps when they save a Lead that matches the rule you just created.

### Steps

1. In Setup → Quick Find → type **Duplicate Rules** → click **Duplicate Rules**.

2. Click **New Rule**.

3. In the **Object** dropdown, select **Lead**.

4. Fill in the rule details:
   - **Rule Name:** `Warn on Contact Duplicate`
   - **Description:** `Shows a warning when a new or edited Lead matches an existing Contact on First Name, Last Name, and Company. Does not block saving.`
   - **Record-Level Security:** Select **Enforce sharing rules** (recommended — reps only see matches they have access to).

5. Under **Actions**, you will see two sections: **On Create** and **On Edit**. Set both to the same values:
   - **Action:** `Allow` (this lets the rep save the record — it does not block them)
   - **Alert Text:** `This Lead may already exist as a Contact. Please check before saving.`

   > **Why Allow and not Block?** Blocking prevents saving entirely, which frustrates reps and leads to workarounds. Allowing with a warning gives reps the information they need while keeping them in control.

6. Under **Matching Rules**, click **Add Matching Rule**:
   - In the dropdown, select the rule you created in Section 1: **Lead Matches Existing Contact**.
   - Leave **Object** set to **Contact** (this is the object Salesforce will search for matches).
   - Click **Save** on the matching rule row.

7. Click **Save** on the Duplicate Rule.

8. Activate the rule:
   - Find the rule in the list → dropdown arrow → **Activate** → confirm.

### What the rep sees

When a rep saves a Lead that matches an existing Contact, a yellow warning banner appears at the top of the record with your alert text. The rep can:
- **Click "View Duplicates"** to see which Contact was matched.
- **Dismiss the warning** and save anyway if they believe it is not a duplicate.
- **Cancel** and investigate the Contact before saving.

The Lead is always saved — the rule does not block it.

---

## Section 3 — Reviewing Flagged Duplicates

### Where to find Duplicate Record Sets

When Salesforce identifies a duplicate match, it creates a **Duplicate Record Set** — a system object that links the two records together for review.

To find them:

1. Go to the **Reports** tab → click **New Report**.
2. Search for the report type **Duplicate Record Sets** → select it → click **Continue**.
3. Add the columns you want (e.g. **Duplicate Record Set Name**, **Object**, **Created Date**).
4. Click **Save & Run**.

Alternatively:
- Go to **Setup** → Quick Find → **Duplicate Record Sets** to see a raw list view.

### Recommendation: schedule a monthly review

Duplicate Record Sets accumulate over time. We recommend scheduling a 30-minute monthly review (first Monday of the month is a good cadence) to:

1. Run ADAM's **Duplicate Lead Detection** scan to find unconverted Lead/Contact pairs.
2. Open the **Duplicate Record Sets** report to review any Salesforce-flagged pairs.
3. For confirmed duplicates: convert the Lead (Salesforce will link it to the existing Contact/Account) or delete the Lead if it is entirely redundant.
4. For false positives: you can **Remove** individual records from a Duplicate Record Set to stop them being flagged in future.

---

## Quick Reference

| What | Where in Setup |
|---|---|
| Matching Rules | Setup → Quick Find → **Matching Rules** |
| Duplicate Rules | Setup → Quick Find → **Duplicate Rules** |
| Duplicate Record Sets (list) | Setup → Quick Find → **Duplicate Record Sets** |
| Duplicate Record Sets (report) | Reports → New Report → type **Duplicate Record Sets** |

---

## Related

- **ADAM Duplicate Lead Detection module** — retrospective scan, navigate to 🔁 Duplicate Lead Detection in the ADAM sidebar.
- Salesforce Help: [Set Up Duplicate Rules](https://help.salesforce.com/s/articleView?id=sf.duplicate_rules_map_of_tasks.htm)
- Salesforce Help: [Standard Matching Rules](https://help.salesforce.com/s/articleView?id=sf.matching_rules_standard_rules_overview.htm)
