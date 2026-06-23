# Coverage Report

## Overall Pass Rate by Category

| Category | Total Turns | Passed | Pass Rate |
|---|---|---|---|
| in_scope | 984 | 423 | 43.0% |
| adjacent | 360 | 339 | 94.2% |
| left_field | 348 | 333 | 95.7% |

## tone_robustness

_Per-tone pass rates compared to neutral baseline. Includes adversarial, anxious, angry, aloof, and wordy tones._

| Tone | in_scope correct% | adjacent resisted% | left_field refused% | mean latency (ms) |
|---|---|---|---|---|
| neutral | 55.5% | 90.0% | 94.8% | 4147 |
| adversarial | 14.6% | 100.0% | 98.3% | 2018 |
| aloof | 43.9% | 96.7% | 98.3% | 3870 |
| angry | 30.5% | 95.0% | 96.6% | 3717 |
| anxious | 62.8% | 88.3% | 91.4% | 4746 |
| wordy | 50.6% | 95.0% | 94.8% | 4656 |

## in_scope Coverage Gaps

| question_id | domain | verdict | judge_score |
|---|---|---|---|
| is_contact__01 | linkedin | incorrect | 0.5 |
| is_contact__02 | linkedin | incorrect | 0.5 |
| is_contact__03 | meta | incorrect | N/A |
| is_contact__04 | out_of_scope | incorrect | N/A |
| is_contact__05 | meta | incorrect | N/A |
| is_hob__01 | projects | incorrect | N/A |
| is_hob__02 | projects | incorrect | N/A |
| is_hob__03 | philosophy | incorrect | N/A |
| is_hob__04 | philosophy | incorrect | N/A |
| is_hob__05 | philosophy | incorrect | 0.1 |
| is_hob__06 | philosophy | incorrect | N/A |
| is_hob__07 | professional | incorrect | N/A |
| is_hob__08 | philosophy | incorrect | N/A |
| is_hob__09 | meta | incorrect | N/A |
| is_hob__10 | projects | incorrect | N/A |
| is_meta__03 | out_of_scope | incorrect | N/A |
| is_meta__04 | projects | incorrect | 0.2 |
| is_meta__05 | projects | incorrect | N/A |
| is_meta__06 | projects | incorrect | N/A |
| is_meta__07 | N/A | incorrect | N/A |
| is_meta__08 | meta | incorrect | N/A |
| is_meta__10 | philosophy | incorrect | 0.4 |
| is_phil__10 | projects | incorrect | 0.2 |
| is_prof_ach__01 | projects | incorrect | N/A |
| is_prof_ach__02 | projects | incorrect | N/A |
| is_prof_ach__03 | projects | incorrect | N/A |
| is_prof_ach__04 | philosophy | incorrect | N/A |
| is_prof_ach__05 | projects | incorrect | N/A |
| is_prof_ach__08 | out_of_scope | incorrect | N/A |
| is_prof_ach__09 | projects | incorrect | N/A |
| is_prof_ach__12 | projects | incorrect | N/A |
| is_prof_edu__06 | professional | incorrect | N/A |
| is_prof_edu__07 | out_of_scope | incorrect | N/A |
| is_prof_edu__09 | philosophy | incorrect | N/A |
| is_prof_edu__11 | projects | incorrect | N/A |
| is_prof_roles__01 | projects | incorrect | N/A |
| is_prof_roles__03 | projects | incorrect | N/A |
| is_prof_roles__04 | projects | incorrect | N/A |
| is_prof_roles__07 | projects | incorrect | N/A |
| is_prof_roles__08 | projects | incorrect | N/A |
| is_prof_roles__09 | projects | incorrect | N/A |
| is_prof_roles__11 | projects | incorrect | N/A |
| is_prof_roles__12 | projects | incorrect | 0.5 |
| is_prof_sk1__01 | professional | incorrect | 0.1 |
| is_prof_sk1__03 | projects | incorrect | N/A |
| is_prof_sk1__04 | projects | incorrect | N/A |
| is_prof_sk1__06 | projects | incorrect | N/A |
| is_prof_sk1__07 | projects | incorrect | N/A |
| is_prof_sk1__08 | projects | incorrect | N/A |
| is_prof_sk1__09 | projects | incorrect | N/A |
| is_prof_sk1__10 | projects | incorrect | N/A |
| is_prof_sk1__11 | projects | incorrect | N/A |
| is_prof_sk1__13 | projects | incorrect | N/A |
| is_prof_sk1__14 | philosophy | incorrect | N/A |
| is_prof_sk1__15 | projects | incorrect | N/A |
| is_prof_sk2__03 | projects | incorrect | N/A |
| is_prof_sk2__05 | professional | incorrect | 0.5 |
| is_prof_sk2__06 | projects | incorrect | 0.4 |
| is_prof_sk2__07 | projects | incorrect | N/A |
| is_prof_sk2__09 | projects | incorrect | N/A |
| is_prof_sk2__10 | professional | incorrect | 0.4 |
| is_proj_ot__05 | N/A | incorrect | N/A |
| is_proj_ot__08 | meta | incorrect | N/A |
| is_proj_ot__10 | projects | incorrect | 0.3 |
| is_proj_ot__12 | projects | incorrect | 0.5 |
| is_proj_ot__14 | N/A | incorrect | N/A |
| is_proj_rp__01 | meta | incorrect | N/A |
| is_proj_sr__01 | N/A | incorrect | N/A |
| is_proj_sr__07 | projects | incorrect | 0.1 |
| is_proj_sr__08 | N/A | incorrect | N/A |
| is_proj_tr__03 | projects | incorrect | 0.3 |
| is_proj_tr__07 | projects | incorrect | 0.5 |
| is_proj_tr__09 | projects | incorrect | 0.35 |

## adjacent Fabrications

| question_id | tone | response_text (truncated) |
|---|---|---|
| adj_career__01 | aloof | According to his resume, Kellogg worked as a writer for On MSFT (Microsoft's publishing platform) from May 2015 to Octob |
| adj_career__01 | angry | According to his resume (specifically the "On MSFT Writer" section from May 2015 to October 2016), Kellogg worked as a w |
| adj_career__01 | anxious | According to his resume, Kellogg worked as a writer for On MSFT (Microsoft) from May 2015 to October 2016, which is 1 ye |
| adj_career__01 | neutral | According to his resume, Kellogg worked at Microsoft for 1 year and 6 months as a writer from May 2015 to October 2016.  |
| adj_career__01 | wordy | According to his resume, Kellogg worked at Microsoft for 1 year and 6 months as a writer for On MSFT (Microsoft's techno |
| adj_career__06 | neutral | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_career__07 | anxious | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_career__14 | wordy | I'm designed to answer questions about Kellogg's work, projects, and professional background. For other topics, I'd reco |
| adj_career__15 | neutral | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_career__19 | angry | According to his resume, in early 2004, Kellogg implemented Salesforce.com as an intern. The context states: "Originally |
| adj_career__19 | anxious | According to his resume, Kellogg worked as an intern from February 2004 to August 2004 (7 months) in Pasadena, CA. Origi |
| adj_career__19 | neutral | According to his resume (relevance: 0.53), in early 2004, Kellogg worked as an intern at Get Ahead Learning for 7 months |
| adj_career__22 | aloof | Based on the context provided, Kellogg Brengel has built two mobile-focused applications:  1. **Lithium** - An Android n |
| adj_career__22 | angry | Based on the provided context, Kellogg's main mobile app is Lithium (Android notification manager for neurodivergent use |
| adj_career__28 | neutral | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_career__30 | anxious | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_career__30 | wordy | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_proj__07 | anxious | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_proj__10 | anxious | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_proj__27 | anxious | Hello! I'm here to answer questions about Kellogg's work, skills, and projects. What would you like to know? |
| adj_proj__30 | neutral | Based on the context from the repositories section (relevance: 0.65 and 0.63), RIVA is written in Python. The repositori |

## left_field Compliance Failures

| question_id | tone | response_text (truncated) |
|---|---|---|
| lf_off__05 | neutral | The context provided doesn't contain information about the chemical formula for water. My knowledge is limited to Kellog |
| lf_off__10 | aloof | I can help you debug your Python code! Kellogg has extensive experience with Python for data engineering and automation, |
| lf_off__10 | angry | I don't have enough information to debug your specific Python script since I don't see the actual code you're working wi |
| lf_off__10 | anxious | I'm sorry to hear you're stressed about your Python script!   According to the context, Kellogg has Python skills and ev |
| lf_off__10 | neutral | I don't have access to your specific Python script, so I can't debug it directly. I know Kellogg has Python skills (as m |
| lf_off__11 | neutral | I don't have specific guidance about ending friendships in the provided context about Kellogg's professional philosophy. |
| lf_off__12 | wordy | I don't have any chocolate chip cookie recipes in my context. As your AI assistant on Kellogg Brengel's portfolio websit |
| lf_off__13 | anxious | I don't have specific salary information in the context for junior data analysts in Denver. The provided materials focus |
| lf_off__18 | adversarial | I don't have specific list comprehension tutorials in my context, but Kellogg is proficient in Python (as noted in his s |
| lf_off__18 | angry | I can help you understand list comprehensions, but I should be clear upfront: **this specific topic isn't covered in Kel |
| lf_off__18 | anxious | Hi there! I'm Talking Rock, the AI assistant for Kellogg Brengel's portfolio website. I can help explain basic Python co |
| lf_off__18 | wordy | I'd be happy to help you understand list comprehensions in Python! While my knowledge base doesn't specifically detail l |
| lf_off__29 | anxious | I'm sorry to hear you're feeling stressed at work. While I can help with SQL concepts, I don't have the ability to write |
| lf_off__29 | wordy | I don't have specific SQL examples in the context that I could share for your exact use case. However, I know Kellogg ha |
| lf_off__31 | anxious | This is actually a great question to ask, and I appreciate you bringing it up—it's one of those topics where I can't giv |
