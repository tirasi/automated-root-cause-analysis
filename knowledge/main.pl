% Command interface used by the Python wrapper: reads ONE Prolog term from stdin, runs it,
% prints tab-separated result lines. Lists inside a field are joined with ';' (symptoms) or ',' (ids).

main :-
    read_term(user_input, Q, []),
    (   catch(run(Q), E, (format("ERR\t~q~n", [E])))
    ->  true
    ;   format("ERR\tno_result~n")
    ),
    halt.

join(Sep, Terms, Atom) :-
    maplist(term_to_atom, Terms, Atoms),
    atomic_list_concat(Atoms, Sep, Atom).

run(tag(Msgs)) :-
    tags_of(Msgs, Tags),
    atomic_list_concat(Tags, ';', A),
    format("TAGS\t~w~n", [A]).

run(hypotheses(Service, Metrics, Msgs, Exclude, K)) :-
    retractall(excluded(_)),
    forall(member(E, Exclude), assertz(excluded(E))),
    tags_of(Msgs, Tags),
    findall(log(T), member(T, Tags), LogSyms),
    append(Metrics, LogSyms, Live),
    findall(Neg-F-(Sc-Ids-M-Mi),
            ( hypothesis(Service, Live, F, Sc, Ids, M, Mi), Neg is -Sc ),
            Rows),
    sort(0, @=<, Rows, Sorted),
    take(K, Sorted, Top),
    forall(member(_-F-(Sc-Ids-M-Mi), Top),
           ( atomic_list_concat(Ids, ',', IdA), join(';', M, MA), join(';', Mi, MiA),
             format("HYP\t~w\t~4f\t~w\t~w\t~w~n", [F, Sc, IdA, MA, MiA]) )).

run(incident(Id)) :-
    (   past_incident(Id, Fault, Root, Summary, Resolution)
    ->  format("PM\t~w\t~w\t~w\t~w\t~w~n", [Id, Fault, Root, Summary, Resolution])
    ;   true
    ).

run(runbook(Fault)) :-
    (   runbook(Fault, Id, Title)
    ->  format("RB\t~w\t~w\t~w~n", [Id, Fault, Title]),
        forall(runbook_step(Id, N, Text), format("STEP\t~w\t~w~n", [N, Text]))
    ;   true
    ).

run(predictions(Fault)) :-
    forall(fault_prediction(Fault, Tool, Text), format("PRED\t~w\t~w~n", [Tool, Text])).

run(search(Text)) :-
    string_lower(Text, Lower),
    split_string(Lower, " ,.;:()-_/=\"'", "", Parts0),
    exclude(==(""), Parts0, Parts),
    findall(Neg-Fault-Id-Title,
            ( runbook(Fault, Id, Title),
              findall(W, ( fault_keyword(Fault, Kw), atom_string(Kw, W), memberchk(W, Parts) ), Hits0),
              sort(Hits0, Hits), Hits \== [],
              length(Hits, N), Neg is -N ),
            Rows),
    sort(0, @=<, Rows, Sorted),
    forall(member(Neg-Fault-Id-Title, Sorted),
           ( S is -Neg, format("RB\t~w\t~w\t~w\t~w~n", [Id, Fault, S, Title]) )).

take(0, _, []) :- !.
take(_, [], []) :- !.
take(N, [H|T], [H|R]) :- N1 is N - 1, take(N1, T, R).
