# Compact Qwen migration corpus

Profile: `compact` (revision 1). Eight unchanged episodes selected from
[the Plan 18.5 corpus](../../18.5-e2e-revalidation/resources/episodes.md).
Original episode numbers, text, importance, context, and chronological order are preserved.
See [compact-corpus-design.md](compact-corpus-design.md) for coverage and limitations.

### Episode 2 -- Team Composition
**Importance**: 0.6
**Context**: "e2e_revalidation_phase1"

```
Met the DataWalk ER team today. Tomek Zbigniew is the tech lead and primary architect. Anya Kowalski handles the Vertica infrastructure and projection optimization. Jonas Weber is the backend engineer working on the normalization pipeline and blocking rules. Sarah Kim specializes in data quality and the evaluation framework. The team follows TDD-first development with pytest, and uses Poetry for Python dependency management. Key principle: "researcher mode" -- prioritize quality metrics (Precision, Recall, F1) over code polish.
```

### Episode 4 -- Normalized Tables Architecture
**Importance**: 0.7
**Context**: "e2e_revalidation_phase1"

```
Stage 1 produces ~15 normalized tables from raw entity data. Key tables: person_normalized_data (core attributes via ParseHumanName, ParseDate, FixUnicodeText UDXs), phones_normalized (E.164 format via ParsePhoneNumber), addresses_normalized (Libpostal normalization), online_identities_normalized (email/website domain extraction), identifiers_normalized (SSN, passport, NPI validation). All CREATE TABLE statements include ORDER BY + SEGMENTED BY clauses for local joins. Feature tables have buddy projections segmented by entity_object_id for scoring co-location. Blocking projections ordered by (feature_value, delta_batch_id, entity_object_id).
```

### Episode 5 -- Feature Catalog
**Importance**: 0.6
**Context**: "e2e_revalidation_phase1"

```
Reviewed the feature engineering specification. The system defines 39 atomic features for person entities and 27 for organization entities. Person features span: name components (given, family, full name similarity), date of birth (exact, year, decade), phone (E.164 normalized, country code), email (full, domain, local part), address (street, city, postal, country), and identifiers (SSN, passport, NPI). Organization features cover: legal name, trade name, business ID, incorporation details. There are also 15 composite features combining multiple atomics (e.g., NAMEPHONE = phonetic_family_name + phone_e164, NAMEDATE = phonetic_given + birth_year). Each feature has per-entity regex exclusion patterns to filter garbage values (keyboard walks, system defaults, repeating chars).
```

### Episode 10 -- SQL Injection in IdentifierLinkNormalizationService
**Importance**: 0.7
**Context**: "e2e_revalidation_phase2"

```
Found a SQL injection vulnerability in the IdentifierLinkNormalizationService during code review. The service was constructing SQL queries using string interpolation for identifier type names, which come from user-provided data mapping configuration. An identifier_type value like "SSN'; DROP TABLE person_normalized_data; --" would execute arbitrary SQL against Vertica. Fixed by switching to parameterized queries using the db/quoting.py helpers (quote_identifier for column/table names, parameterized $1/$2 for values). Also audited all other normalization services -- phone_link_service.py and address_link_service.py had similar patterns. All fixed and covered by new unit tests.
```

### Episode 18 -- Metaphone3 Evaluation: 4-Char Concerns
**Importance**: 0.7
**Context**: "e2e_revalidation_phase3"

```
Evaluated Metaphone3 as a replacement for Soundex in our phonetic blocking rules. Metaphone3 offers >98% accuracy on the reference corpus vs Soundex's ~70%. However, the default 4-character code length creates too many candidate pairs -- with 252M entities, 4-char Metaphone3 codes map to very large equivalence classes. For example, "SMITH" and "SCHMIDT" both produce code "XMT0" (4-char), creating a block of potentially millions of pairs. The pair explosion at 4-char is worse than Soundex because Metaphone3's normalization is more aggressive about collapsing similar sounds. We need to investigate longer code lengths or combined blocking keys to control block sizes while keeping the accuracy benefit.
```

### Episode 20 -- Switching to 8-Char Metaphone3
**Importance**: 0.7
**Context**: "e2e_revalidation_phase3"

```
Decision made: switching from 4-character to 8-character Metaphone3 codes for all phonetic blocking rules. The 8-char codes are more discriminative -- "SMITH" (XMT0) vs "SCHMIDT" (XMTT) are now distinct, reducing block sizes by approximately 60%. Migrated all person blocking rules (rules P1-P8) and organization blocking rules (rules O1-O5) to use Metaphone3 with maxCodeLen=8. Also replaced DoubleMetaphone with Metaphone3 for organization name blocking. The Metaphone3 UDX is implemented as a Java function in vertica-functions-datawalk-library.jar with configurable parameters: maxCodeLen, encodeVowels (false), encodeExact (false). Benchmarking the impact on pair counts and recall at 1M scale before scaling up.
```

### Episode 26 -- CORRECTION: Metaphone3 Hybrid Approach
**Importance**: 0.8
**Context**: "e2e_revalidation_phase4_correction"

```
CORRECTION to the previous Metaphone3 decision. After testing with multilingual datasets, the 8-character Metaphone3 codes are too discriminative for non-Latin scripts. Korean, Chinese, and Arabic names transliterated to Latin produce highly variable Metaphone3 codes -- the same name can produce 3-4 different 8-char codes depending on the romanization scheme used. This effectively breaks phonetic blocking for non-Latin names. New decision: HYBRID APPROACH -- use 8-character Metaphone3 for Latin-script names (where the longer codes improve precision) and 4-character Metaphone3 for non-Latin transliterated names (where shorter codes provide necessary recall). Implemented via a language detection step before phonetic encoding. This reverses the blanket "switch to 8-char" decision from Episode 20.
```

### Episode 27 -- Team Change
**Importance**: 0.6
**Context**: "e2e_revalidation_phase4_correction"

```
Team restructuring: Jonas Weber has transferred from the ER backend team to the Security team, effective this week. This was motivated by the SQL injection findings from Episode 10 -- leadership decided to invest more in security infrastructure. Sarah Kim is taking over Jonas's backend engineering responsibilities on the ER project, in addition to her data quality work. Sarah is now the primary owner of the normalization pipeline and blocking rules implementation. Anya Kowalski continues as Vertica infrastructure lead. The team is now three people instead of four, so we're reprioritizing: collective entity resolution (from the gap analysis) is deferred to Q3.
```
