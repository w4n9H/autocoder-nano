# Generated from DSLSQL.g4 by ANTLR 4.7.1
from antlr4 import *
if __name__ is not None and "." in __name__:
    from .DSLSQLParser import DSLSQLParser
else:
    from DSLSQLParser import DSLSQLParser

# This class defines a complete listener for a parse tree produced by DSLSQLParser.
class DSLSQLListener(ParseTreeListener):

    # Enter a parse tree produced by DSLSQLParser#statement.
    def enterStatement(self, ctx:DSLSQLParser.StatementContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#statement.
    def exitStatement(self, ctx:DSLSQLParser.StatementContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#sql.
    def enterSql(self, ctx:DSLSQLParser.SqlContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#sql.
    def exitSql(self, ctx:DSLSQLParser.SqlContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#overwrite.
    def enterOverwrite(self, ctx:DSLSQLParser.OverwriteContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#overwrite.
    def exitOverwrite(self, ctx:DSLSQLParser.OverwriteContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#append.
    def enterAppend(self, ctx:DSLSQLParser.AppendContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#append.
    def exitAppend(self, ctx:DSLSQLParser.AppendContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#errorIfExists.
    def enterErrorIfExists(self, ctx:DSLSQLParser.ErrorIfExistsContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#errorIfExists.
    def exitErrorIfExists(self, ctx:DSLSQLParser.ErrorIfExistsContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#ignore.
    def enterIgnore(self, ctx:DSLSQLParser.IgnoreContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#ignore.
    def exitIgnore(self, ctx:DSLSQLParser.IgnoreContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#booleanExpression.
    def enterBooleanExpression(self, ctx:DSLSQLParser.BooleanExpressionContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#booleanExpression.
    def exitBooleanExpression(self, ctx:DSLSQLParser.BooleanExpressionContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#expression.
    def enterExpression(self, ctx:DSLSQLParser.ExpressionContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#expression.
    def exitExpression(self, ctx:DSLSQLParser.ExpressionContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#ender.
    def enterEnder(self, ctx:DSLSQLParser.EnderContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#ender.
    def exitEnder(self, ctx:DSLSQLParser.EnderContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#format_type.
    def enterFormat_type(self, ctx:DSLSQLParser.Format_typeContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#format_type.
    def exitFormat_type(self, ctx:DSLSQLParser.Format_typeContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#path.
    def enterPath(self, ctx:DSLSQLParser.PathContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#path.
    def exitPath(self, ctx:DSLSQLParser.PathContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#setValue.
    def enterSetValue(self, ctx:DSLSQLParser.SetValueContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#setValue.
    def exitSetValue(self, ctx:DSLSQLParser.SetValueContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#setKey.
    def enterSetKey(self, ctx:DSLSQLParser.SetKeyContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#setKey.
    def exitSetKey(self, ctx:DSLSQLParser.SetKeyContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#db.
    def enterDb(self, ctx:DSLSQLParser.DbContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#db.
    def exitDb(self, ctx:DSLSQLParser.DbContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#tableName.
    def enterTableName(self, ctx:DSLSQLParser.TableNameContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#tableName.
    def exitTableName(self, ctx:DSLSQLParser.TableNameContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#functionName.
    def enterFunctionName(self, ctx:DSLSQLParser.FunctionNameContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#functionName.
    def exitFunctionName(self, ctx:DSLSQLParser.FunctionNameContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#col.
    def enterCol(self, ctx:DSLSQLParser.ColContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#col.
    def exitCol(self, ctx:DSLSQLParser.ColContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#qualifiedName.
    def enterQualifiedName(self, ctx:DSLSQLParser.QualifiedNameContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#qualifiedName.
    def exitQualifiedName(self, ctx:DSLSQLParser.QualifiedNameContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#identifier.
    def enterIdentifier(self, ctx:DSLSQLParser.IdentifierContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#identifier.
    def exitIdentifier(self, ctx:DSLSQLParser.IdentifierContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#strictIdentifier.
    def enterStrictIdentifier(self, ctx:DSLSQLParser.StrictIdentifierContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#strictIdentifier.
    def exitStrictIdentifier(self, ctx:DSLSQLParser.StrictIdentifierContext):
        pass


    # Enter a parse tree produced by DSLSQLParser#quotedIdentifier.
    def enterQuotedIdentifier(self, ctx:DSLSQLParser.QuotedIdentifierContext):
        pass

    # Exit a parse tree produced by DSLSQLParser#quotedIdentifier.
    def exitQuotedIdentifier(self, ctx:DSLSQLParser.QuotedIdentifierContext):
        pass

