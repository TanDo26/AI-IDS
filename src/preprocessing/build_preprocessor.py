from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer


def build_preprocessor(numeric_features, categorical_features, config):

    imputer_strategy = "median"

    if config:
        imputer_strategy = config.get("preprocessing",{}).get("imputer_strategy", "median")

    numeric_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy=imputer_strategy)),
        ("scaler", StandardScaler())
    ])

    transformers = [("numeric", numeric_pipeline, numeric_features)]

    if categorical_features:
        categorical_pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore",sparse_output=False))
        ])

        transformers.append(("categorical", categorical_pipeline, categorical_features))

    return ColumnTransformer(transformers, remainder="drop")