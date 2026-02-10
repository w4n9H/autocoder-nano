# Generated from DSLSQL.g4 by ANTLR 4.7.1
from antlr4 import *
if __name__ is not None and "." in __name__:
    from .DSLSQLParser import DSLSQLParser
else:
    from DSLSQLParser import DSLSQLParser

# This class defines a complete generic visitor for a parse tree produced by DSLSQLParser.

class DSLSQLVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by DSLSQLParser#statement.
    def visitStatement(self, ctx:DSLSQLParser.StatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#sql.
    def visitSql(self, ctx:DSLSQLParser.SqlContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#overwrite.
    def visitOverwrite(self, ctx:DSLSQLParser.OverwriteContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#append.
    def visitAppend(self, ctx:DSLSQLParser.AppendContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#errorIfExists.
    def visitErrorIfExists(self, ctx:DSLSQLParser.ErrorIfExistsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#ignore.
    def visitIgnore(self, ctx:DSLSQLParser.IgnoreContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#booleanExpression.
    def visitBooleanExpression(self, ctx:DSLSQLParser.BooleanExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#expression.
    def visitExpression(self, ctx:DSLSQLParser.ExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#ender.
    def visitEnder(self, ctx:DSLSQLParser.EnderContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#format_type.
    def visitFormat_type(self, ctx:DSLSQLParser.Format_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#path.
    def visitPath(self, ctx:DSLSQLParser.PathContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#setValue.
    def visitSetValue(self, ctx:DSLSQLParser.SetValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#setKey.
    def visitSetKey(self, ctx:DSLSQLParser.SetKeyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#db.
    def visitDb(self, ctx:DSLSQLParser.DbContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#tableName.
    def visitTableName(self, ctx:DSLSQLParser.TableNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#functionName.
    def visitFunctionName(self, ctx:DSLSQLParser.FunctionNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#col.
    def visitCol(self, ctx:DSLSQLParser.ColContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#qualifiedName.
    def visitQualifiedName(self, ctx:DSLSQLParser.QualifiedNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#identifier.
    def visitIdentifier(self, ctx:DSLSQLParser.IdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#strictIdentifier.
    def visitStrictIdentifier(self, ctx:DSLSQLParser.StrictIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DSLSQLParser#quotedIdentifier.
    def visitQuotedIdentifier(self, ctx:DSLSQLParser.QuotedIdentifierContext):
        return self.visitChildren(ctx)



del DSLSQLParser