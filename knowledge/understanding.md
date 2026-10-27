The order: fault prediction does not come first. 
A guess has to exist before there’s anything to test, and the guess comes from the past cases. The full order is:

Detect: the detector notices something wrong and finds the first service that broke.

Guess: the KB compares the symptoms with incidents.pl and rules.pl, and returns a ranked guess such as “probably bad_deploy”.

Test: fault_prediction is looked up for that guess. It says which tool to call and what to expect if the guess is true.

Fix: if the tool results match, the runbook_step lines say what to do.

A naming trap

The name fault_prediction is misleading. It doesn’t predict which fault is happening. It means “if this fault is true, I predict I’ll see this”. It’s a test for a guess.