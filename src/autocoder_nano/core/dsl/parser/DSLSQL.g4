grammar DSLSQL;

statement
    : (sql ender)*
    ;


sql
    : ('load'|'LOAD') format_type '.' path ('options'|'where')? expression? booleanExpression*  'as' tableName
    | ('save'|'SAVE') (overwrite | append | errorIfExists |ignore)* tableName 'as' format_type '.' path ('options'|'where')? expression? booleanExpression* ('partitionBy' col)?
    | ('select'|'SELECT') ~(';')* 'as' tableName
    | ('insert'|'INSERT') ~(';')*
    | ('create'|'CREATE') ~(';')*
    | ('drop'|'DROP') ~(';')*
    | ('refresh'|'REFRESH') ~(';')*
    | ('set'|'SET') setKey '=' setValue ('options'|'where')? expression? booleanExpression*
    | ('connect'|'CONNECT') format_type ('options'|'where')? expression? booleanExpression* ('as' db)?
    | ('train'|'TRAIN'|'run'|'RUN') tableName 'as' format_type '.' path ('options'|'where')? expression? booleanExpression*
    | ('register'|'REGISTER') format_type '.' path 'as' functionName ('options'|'where')? expression? booleanExpression*
    | ('unRegister'|'UNREGISTER') format_type '.' path ('options'|'where')? expression? booleanExpression*
    | ('include'|'INCLUDE') format_type '.' path ('options'|'where')? expression? booleanExpression*
    |  SIMPLE_COMMENT
    ;

overwrite
    : 'overwrite'
    ;

append
    : 'append'
    ;

errorIfExists
    : 'errorIfExists'
    ;

ignore
    : 'ignore'
    ;

booleanExpression
    : 'and' expression
    ;

expression
    : identifier '=' STRING
    ;

ender
    :';'
    ;

format_type
    : identifier
    ;

path
    : quotedIdentifier | identifier
    ;

setValue
    : qualifiedName | quotedIdentifier | STRING | BLOCK_STRING
    ;

setKey
    : qualifiedName
    ;

db
    :qualifiedName | identifier
    ;

tableName
    : identifier
    ;

functionName
    : identifier
    ;

col
    : identifier
    ;

qualifiedName
    : identifier ('.' identifier)*
    ;

identifier
    : strictIdentifier
    ;

strictIdentifier
    : IDENTIFIER
    | quotedIdentifier
    ;

quotedIdentifier
    : BACKQUOTED_IDENTIFIER
    ;


STRING
    : '\'' ( ~('\''|'\\') | ('\\' .) )* '\''
    | '"' ( ~('"'|'\\') | ('\\' .) )* '"'
    ;

BLOCK_STRING
    : '\'\'\'' ~[+] .*? '\'\'\''
    ;

IDENTIFIER
    : (LETTER | DIGIT | '_')+
    ;

BACKQUOTED_IDENTIFIER
    : '`' ( ~'`' | '``' )* '`'
    ;

fragment DIGIT
    : [0-9]
    ;

fragment LETTER
    : [a-zA-Z]
    ;

SIMPLE_COMMENT
    : '--' ~[\r\n]* '\r'? '\n'? -> channel(HIDDEN)
    ;

BRACKETED_EMPTY_COMMENT
    : '/**/' -> channel(HIDDEN)
    ;

BRACKETED_COMMENT
    : '/*' ~[+] .*? '*/' -> channel(HIDDEN)
    ;

WS
    : [ \r\n\t]+ -> channel(HIDDEN)
    ;

// Catch-all for anything we can't recognize.
// We use this to be able to ignore and recover all the text
// when splitting statements with DelimiterLexer
UNRECOGNIZED
    : .
    ;