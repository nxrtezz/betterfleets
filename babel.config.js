module.exports = {
  presets: [
    '@babel/preset-env',
    ['@babel/preset-react', {runtime: 'automatic'}],
  ],
  overrides: [
    {
      test: /\.tsx?$/,
      presets: [['@babel/preset-typescript', {isTSX: true, allExtensions: true}]],
    },
    {
      test: /\.jsx?$/,
      presets: ['@babel/preset-flow'],
    },
  ],
};
